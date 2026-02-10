"""Main orchestrator that wires together browser, LLM, lists, nutrition, and budget.

This module implements the ToolHandler that the LLM delegates tool calls to,
and the main Agent class that runs the conversational shopping loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from grocery_agent.browser import WalmartBrowser
from grocery_agent.budget import BudgetTracker
from grocery_agent.grocery_list import GroceryListManager
from grocery_agent.llm import GroceryLLM
from grocery_agent.models import CartItem, GroceryItem, WalmartProduct
from grocery_agent.nutrition import format_health_summary, score_items

logger = logging.getLogger(__name__)


class ToolHandler:
    """Handles tool calls from the LLM agent.

    Each handle_* method corresponds to a tool defined in llm.py.
    """

    def __init__(
        self,
        browser: WalmartBrowser,
        list_manager: GroceryListManager,
        budget: BudgetTracker,
    ) -> None:
        self.browser = browser
        self.lists = list_manager
        self.budget = budget
        self._last_search_results: list[WalmartProduct] = []
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

    async def handle_search_walmart(
        self, query: str, max_results: int = 5
    ) -> dict:
        """Search Walmart for products."""
        if not self.browser.is_ready:
            return {"error": "Browser not ready. Please launch the browser first."}

        try:
            results = await self.browser.search_products(query, max_results)
            self._last_search_results = results
            self._last_search_query = query

            products = []
            for i, p in enumerate(results):
                product_info = {
                    "index": i,
                    "name": p.name,
                    "price": p.price,
                    "on_sale": p.on_sale,
                    "in_stock": p.in_stock,
                }
                if p.on_sale:
                    product_info["original_price"] = p.original_price
                    product_info["discount"] = p.discount_pct
                    product_info["sale_badge"] = p.sale_badge
                if p.unit_price:
                    product_info["unit_price"] = p.unit_price
                products.append(product_info)

            sale_items = [p for p in results if p.on_sale]

            return {
                "query": query,
                "result_count": len(results),
                "products": products,
                "sale_count": len(sale_items),
            }
        except Exception as e:
            return {"error": f"Search failed: {str(e)}"}

    async def handle_compare_prices(
        self, item: str, alternatives: list[str] | None = None
    ) -> dict:
        """Compare prices between an item and alternatives."""
        if not self.browser.is_ready:
            return {"error": "Browser not ready."}

        try:
            comparison = await self.browser.search_and_compare(item, alternatives)

            result: dict[str, Any] = {
                "primary_item": item,
                "primary_results": [
                    {"name": p.name, "price": p.price, "on_sale": p.on_sale}
                    for p in comparison["primary_results"][:3]
                ],
                "alternatives": {},
                "sale_suggestions": [],
            }

            for alt_name, alt_products in comparison["alternatives"].items():
                result["alternatives"][alt_name] = [
                    {"name": p.name, "price": p.price, "on_sale": p.on_sale}
                    for p in alt_products[:3]
                ]

            for suggestion in comparison["sale_alternatives"]:
                result["sale_suggestions"].append(suggestion["suggestion"])

            if comparison["best_deal"]:
                bd = comparison["best_deal"]
                result["best_deal"] = {
                    "name": bd.name,
                    "price": bd.price,
                    "on_sale": bd.on_sale,
                }

            return result
        except Exception as e:
            return {"error": f"Comparison failed: {str(e)}"}

    async def handle_add_to_walmart_cart(
        self, search_query: str, product_index: int = 0
    ) -> dict:
        """Search for and add a product to the Walmart cart."""
        if not self.browser.is_ready:
            return {"error": "Browser not ready."}

        try:
            # Search first
            results = await self.browser.search_products(search_query, max_results=5)
            if not results:
                return {"error": f"No results found for '{search_query}'"}

            if product_index >= len(results):
                product_index = 0

            product = results[product_index]

            # Try adding from search results page first
            success = await self.browser.add_to_cart_from_search(product_index)

            if not success:
                # Fall back to navigating to product page
                success = await self.browser.add_to_cart(product)

            if success:
                # Track in budget
                grocery_item = GroceryItem(name=product.name)
                cart_item = CartItem(
                    grocery_item=grocery_item,
                    walmart_product=product,
                )
                budget_status = self.budget.add_item(cart_item)

                return {
                    "success": True,
                    "product": product.name,
                    "price": product.price,
                    "on_sale": product.on_sale,
                    "budget_status": budget_status,
                }
            else:
                return {
                    "success": False,
                    "error": f"Could not add '{product.name}' to cart. "
                    "The page layout may have changed.",
                    "product": product.name,
                }
        except Exception as e:
            return {"error": f"Failed to add to cart: {str(e)}"}

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

    async def handle_get_cart_total(self) -> dict:
        """Get current Walmart cart total."""
        if not self.browser.is_ready:
            return {"error": "Browser not ready."}

        total = await self.browser.get_cart_total()
        if total is not None:
            return {"cart_total": total}
        return {"error": "Could not read cart total"}

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
        """Start shopping - search for each list item on Walmart."""
        items = self.lists.get_items()
        if not items:
            return {"error": "No items in grocery list. Add items first!"}

        if not self.browser.is_ready:
            return {"error": "Browser not ready. Please launch browser first."}

        return {
            "action": "shopping_started",
            "items_to_shop": [item.display() for item in items],
            "item_count": len(items),
            "check_sales": check_sales,
            "instruction": (
                "For each item, search Walmart, show the user the best options "
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

    def __init__(self, headless: bool = True) -> None:
        self.browser = WalmartBrowser(headless=headless)
        self.list_manager = GroceryListManager()
        self.budget = BudgetTracker()
        self.llm = GroceryLLM()
        self.tool_handler = ToolHandler(
            self.browser, self.list_manager, self.budget
        )
        self.llm.set_tool_handler(self.tool_handler)
        self._browser_launched = False

    async def start(self) -> None:
        """Launch the agent: open browser, navigate to Walmart."""
        print("=" * 60)
        print("  Grocery Shopping Agent")
        print("  Powered by Claude + Walmart Browser Automation")
        print("=" * 60)
        print()
        print("Launching browser...")

        await self.browser.launch()
        self._browser_launched = True

        print("Navigating to Walmart...")
        try:
            await self.browser.navigate_to_walmart()
        except Exception as e:
            print(f"\nCould not reach Walmart ({e}). Browser is ready for manual navigation.")

        # Wait for login (short timeout in headless mode)
        login_timeout = 10 if not self.browser.is_headed else 300
        logged_in = await self.browser.wait_for_login(timeout=login_timeout)
        if not logged_in:
            print(
                "\nCouldn't detect login automatically. "
                "You can still continue - I'll try to shop for you."
            )
            if self.browser.is_headed:
                print("If you need to log in, do so in the browser window.\n")

        # Greet the user
        try:
            greeting = await self.llm.chat(
                "The user has just started a grocery shopping session. "
                "The browser is open to Walmart. Greet them warmly and ask about "
                "their shopping needs today - what they want to cook this week, "
                "any dietary requirements, budget, etc. Keep it conversational."
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

            if user_input.lower() == "screenshot":
                path = await self.browser.screenshot()
                print(f"\nScreenshot saved to: {path}\n")
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
        if self._browser_launched:
            try:
                await asyncio.wait_for(self.browser.close(), timeout=3)
            except asyncio.TimeoutError:
                logger.warning("Browser close timed out, forcing exit")
            except Exception as e:
                logger.warning(f"Browser cleanup issue: {e}")
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
  screenshot  - Save browser screenshot
  quit        - Exit and save session

Or just talk naturally! Examples:
  "I want to meal prep for the week, mostly Mediterranean"
  "Add 2 lbs of chicken breast and a bag of brown rice"
  "What's on sale that's similar to salmon?"
  "Set my budget to $150"
  "Start shopping - add everything to my cart"
  "Load my saved 'weekly essentials' list"
""")
