"""Main orchestrator that wires together the Kroger API, LLM, lists, nutrition, and budget.

This module implements the ToolHandler that the LLM delegates tool calls to,
and the main Agent class that runs the conversational shopping loop.
"""

from __future__ import annotations

import logging
from typing import Any

from grocery_agent.budget import BudgetTracker
from grocery_agent.grocery_list import GroceryListManager
from grocery_agent.kroger import KrogerClient
from grocery_agent.llm import GroceryLLM
from grocery_agent.models import CartItem, GroceryItem, KrogerProduct
from grocery_agent.nutrition import format_health_summary, score_items

logger = logging.getLogger(__name__)


class ToolHandler:
    """Handles tool calls from the LLM agent.

    Each handle_* method corresponds to a tool defined in llm.py.
    """

    def __init__(
        self,
        kroger: KrogerClient,
        list_manager: GroceryListManager,
        budget: BudgetTracker,
    ) -> None:
        self.kroger = kroger
        self.lists = list_manager
        self.budget = budget
        self._last_search_results: list[KrogerProduct] = []
        self._last_search_query: str = ""

    async def handle_add_to_grocery_list(
        self,
        name: str,
        quantity: int = 1,
        unit: str = "",
        notes: str = "",
    ) -> dict:
        """Add an item to the grocery list."""
        if not self.lists.active_list:
            self.lists.create_list("Shopping List")

        item = self.lists.add_item(
            name=name, quantity=quantity, unit=unit, notes=notes
        )
        items = self.lists.get_items()
        score = score_items(items)

        return {
            "added": item.display(),
            "category": item.category.value,
            "health_tier": item.health_tier.value,
            "list_size": len(items),
            "health_score": score.health_score,
        }

    async def handle_remove_from_grocery_list(self, item_name: str) -> dict:
        """Remove an item from the grocery list by name."""
        items = self.lists.get_items()
        for item in items:
            if item_name.lower() in item.name.lower():
                removed = self.lists.remove_item(item.id)
                return {"removed": item.name, "success": removed}
        return {"error": f"Item '{item_name}' not found in list"}

    async def handle_show_grocery_list(self) -> dict:
        """Show the current grocery list."""
        gl = self.lists.active_list
        if not gl:
            return {"list": "No active grocery list. Start adding items!"}
        return {
            "list": gl.display(),
            "item_count": len(gl.items),
            "dietary_notes": gl.dietary_notes,
        }

    async def handle_search_kroger(
        self, query: str, max_results: int = 5
    ) -> dict:
        """Search Kroger for products."""
        if not self.kroger.is_configured:
            return {
                "error": "Kroger API credentials not configured. "
                "Set KROGER_CLIENT_ID and KROGER_CLIENT_SECRET env vars."
            }

        try:
            results = self.kroger.search_products(query, max_results)
            self._last_search_results = results
            self._last_search_query = query

            products = []
            for i, p in enumerate(results):
                product_info: dict[str, Any] = {
                    "index": i,
                    "name": p.name,
                    "brand": p.brand,
                    "price": p.effective_price,
                    "on_sale": p.on_sale,
                    "in_stock": p.in_stock,
                }
                if p.on_sale:
                    product_info["regular_price"] = p.price
                    product_info["promo_price"] = p.promo_price
                    product_info["discount"] = p.discount_pct
                products.append(product_info)

            sale_items = [p for p in results if p.on_sale]

            return {
                "query": query,
                "result_count": len(results),
                "products": products,
                "sale_count": len(sale_items),
                "store": self.kroger.location_id or "national (set a store for local prices)",
            }
        except Exception as e:
            return {"error": f"Search failed: {str(e)}"}

    async def handle_compare_prices(
        self, item: str, alternatives: list[str] | None = None
    ) -> dict:
        """Compare prices between an item and alternatives."""
        if not self.kroger.is_configured:
            return {"error": "Kroger API credentials not configured."}

        try:
            comparison = self.kroger.compare_products(item, alternatives)

            result: dict[str, Any] = {
                "primary_item": item,
                "primary_results": [
                    {"name": p.name, "price": p.effective_price, "on_sale": p.on_sale}
                    for p in comparison["primary_results"][:3]
                ],
                "alternatives": {},
                "sale_suggestions": [],
            }

            for alt_name, alt_products in comparison["alternatives"].items():
                result["alternatives"][alt_name] = [
                    {"name": p.name, "price": p.effective_price, "on_sale": p.on_sale}
                    for p in alt_products[:3]
                ]

            for suggestion in comparison["sale_items"]:
                result["sale_suggestions"].append(suggestion["suggestion"])

            if comparison["best_deal"]:
                bd = comparison["best_deal"]
                result["best_deal"] = {
                    "name": bd.name,
                    "price": bd.effective_price,
                    "on_sale": bd.on_sale,
                }

            return result
        except Exception as e:
            return {"error": f"Comparison failed: {str(e)}"}

    async def handle_add_to_cart(
        self, search_query: str, product_index: int = 0
    ) -> dict:
        """Search for and track a product (add to budget tracking)."""
        if not self.kroger.is_configured:
            return {"error": "Kroger API credentials not configured."}

        try:
            results = self.kroger.search_products(search_query, max_results=5)
            if not results:
                return {"error": f"No results found for '{search_query}'"}

            if product_index >= len(results):
                product_index = 0

            product = results[product_index]

            grocery_item = GroceryItem(name=product.name)
            cart_item = CartItem(
                grocery_item=grocery_item,
                product=product,
            )
            budget_status = self.budget.add_item(cart_item)

            return {
                "success": True,
                "product": product.name,
                "price": product.effective_price,
                "on_sale": product.on_sale,
                "budget_status": budget_status,
            }
        except Exception as e:
            return {"error": f"Failed to add to cart: {str(e)}"}

    async def handle_set_store(
        self, zip_code: str, radius_miles: int = 10
    ) -> dict:
        """Find nearby Kroger stores and set the closest one."""
        if not self.kroger.is_configured:
            return {"error": "Kroger API credentials not configured."}

        try:
            stores = self.kroger.search_locations(
                zip_code=zip_code, radius_miles=radius_miles, limit=5
            )
            if not stores:
                return {"error": f"No Kroger stores found near {zip_code}"}

            # Auto-select the first/closest store
            self.kroger.set_location(stores[0]["locationId"])

            return {
                "selected_store": stores[0],
                "nearby_stores": stores,
                "message": f"Set store to {stores[0]['name']} ({stores[0]['address']})",
            }
        except Exception as e:
            return {"error": f"Store search failed: {str(e)}"}

    async def handle_check_nutrition(self) -> dict:
        """Check nutrition score for current list."""
        items = self.lists.get_items()
        if not items:
            return {"message": "No items in list to score."}

        score = score_items(items)
        return {
            "health_score": score.health_score,
            "tier": score.tier.value,
            "total_items": score.total_items,
            "veg_fruit_count": score.veg_fruit_count,
            "protein_count": score.protein_count,
            "whole_grain_count": score.whole_grain_count,
            "processed_count": score.processed_count,
            "suggestions": score.suggestions,
            "formatted": score.display(),
        }

    async def handle_check_budget(self) -> dict:
        """Check budget status."""
        return self.budget.status()

    async def handle_set_budget(self, amount: float) -> dict:
        """Set the shopping budget."""
        self.budget.set_budget(amount)
        return {
            "budget_set": amount,
            "message": f"Budget set to ${amount:.2f}",
        }

    async def handle_save_list(self, name: str) -> dict:
        """Save the current grocery list."""
        if not self.lists.active_list:
            return {"error": "No active list to save."}

        self.lists.active_list.name = name
        path = self.lists.save_list()
        return {"saved": name, "path": path}

    async def handle_load_saved_list(self, name: str) -> dict:
        """Load a saved grocery list."""
        gl = self.lists.load_list(name)
        if gl:
            return {
                "loaded": gl.name,
                "items": len(gl.items),
                "list": gl.display(),
            }
        return {"error": f"No saved list named '{name}'"}

    async def handle_show_saved_lists(self) -> dict:
        """Show all saved lists."""
        saved = self.lists.list_saved()
        return {"saved_lists": saved, "count": len(saved)}

    async def handle_create_meal_plan(
        self,
        days: int = 7,
        people: int = 2,
        preferences: str = "",
        budget: float = 0,
    ) -> dict:
        """Create a meal plan. Returns context for the LLM to generate meals."""
        return {
            "action": "generate_meal_plan",
            "days": days,
            "people": people,
            "preferences": preferences,
            "budget": budget,
            "instruction": (
                "Please generate a meal plan with these parameters and "
                "then add the ingredients to the grocery list using "
                "add_to_grocery_list for each item."
            ),
        }

    async def handle_start_shopping(self, check_sales: bool = True) -> dict:
        """Start shopping - search for each list item on Kroger."""
        items = self.lists.get_items()
        if not items:
            return {"error": "No items in grocery list. Add items first!"}

        if not self.kroger.is_configured:
            return {"error": "Kroger API credentials not configured."}

        return {
            "action": "shopping_started",
            "items_to_shop": [item.display() for item in items],
            "item_count": len(items),
            "check_sales": check_sales,
            "store": self.kroger.location_id or "national",
            "instruction": (
                "For each item, search Kroger, show the user the best options "
                "(including any sale items), and ask which one to add to cart. "
                "If check_sales is True, also search for similar/alternative items "
                "that might be on sale."
            ),
        }

    async def handle_spending_history(self) -> dict:
        """Show spending history."""
        return {"history": BudgetTracker.get_spending_history()}


class GroceryAgent:
    """Main agent that runs the grocery shopping experience."""

    def __init__(self) -> None:
        self.kroger = KrogerClient()
        self.list_manager = GroceryListManager()
        self.budget = BudgetTracker()
        self.llm = GroceryLLM()
        self.tool_handler = ToolHandler(
            self.kroger, self.list_manager, self.budget
        )
        self.llm.set_tool_handler(self.tool_handler)

    async def start(self) -> None:
        """Initialize the agent and greet the user."""
        print("=" * 60)
        print("  Grocery Shopping Agent")
        print("  Powered by Claude + Kroger API")
        print("=" * 60)
        print()

        if self.kroger.is_configured:
            print("Kroger API: connected")
        else:
            print("Kroger API: not configured")
            print("  Set KROGER_CLIENT_ID and KROGER_CLIENT_SECRET to enable shopping.")
            print("  Register free at https://developer.kroger.com\n")

        # Greet the user
        try:
            greeting = await self.llm.chat(
                "The user has just started a grocery shopping session. "
                "Greet them warmly and ask about their shopping needs today - "
                "what they want to cook this week, any dietary requirements, "
                "budget, etc. Keep it conversational. "
                + (
                    "The Kroger API is connected and ready for product searches."
                    if self.kroger.is_configured
                    else "Note: Kroger API credentials aren't set yet, but you "
                    "can still help with meal planning, list management, and nutrition."
                )
            )
            print(f"\nAssistant: {greeting}\n")
        except Exception as e:
            print(f"\nCould not connect to Claude API: {e}")
            print("You can still use local commands: list, budget, nutrition, help\n")

    async def chat(self, user_input: str) -> str:
        """Process user input and return the agent's response."""
        response = await self.llm.chat(user_input)
        return response

    async def run_interactive(self) -> None:
        """Run the full interactive shopping loop."""
        await self.start()

        print("Type 'quit' to exit, 'help' for commands.\n")

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye! Happy cooking!")
                break

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit", "bye"):
                # Save session
                self.budget.save_session()
                print("\nSession saved. Goodbye! Happy cooking!")
                break

            if user_input.lower() == "help":
                self._print_help()
                continue

            if user_input.lower() == "budget":
                print(f"\n{self.budget.format_status()}\n")
                continue

            if user_input.lower() == "list":
                print(f"\n{self.list_manager.display_list()}\n")
                continue

            if user_input.lower() == "nutrition":
                items = self.list_manager.get_items()
                print(f"\n{format_health_summary(items)}\n")
                continue

            # Send to LLM
            try:
                response = await self.llm.chat(user_input)
                print(f"\nAssistant: {response}\n")
            except Exception as e:
                print(f"\nError: {e}")
                print("Let me try again...\n")

    async def shutdown(self) -> None:
        """Clean up resources."""
        self.kroger.close()
        try:
            self.budget.save_session()
        except Exception:
            pass

    @staticmethod
    def _print_help() -> None:
        print("""
Commands:
  help        - Show this help
  list        - Show current grocery list
  budget      - Show budget status
  nutrition   - Show nutrition score
  quit        - Exit and save session

Or just talk naturally! Examples:
  "I want to meal prep for the week, mostly Mediterranean"
  "Add 2 lbs of chicken breast and a bag of brown rice"
  "Search Kroger for organic eggs"
  "What's on sale that's similar to salmon?"
  "Set my budget to $150"
  "Find a Kroger near 90210"
  "Start shopping - find prices for everything on my list"
  "Load my saved 'weekly essentials' list"
""")
