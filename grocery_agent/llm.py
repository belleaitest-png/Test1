"""LLM agent powered by Claude for natural language grocery assistance.

Handles conversation, meal planning, dietary advice, and coordinates
the browser automation and list management via tool use.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import anthropic

from grocery_agent.config import DEFAULT_MODEL
from grocery_agent.models import GroceryItem

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a friendly, knowledgeable grocery shopping assistant. You help users:

1. **Plan meals and build grocery lists** based on their dietary needs, preferences, and health goals.
2. **Optimize shopping** by suggesting sales, substitutions, and budget-friendly alternatives.
3. **Track nutrition** at a high level (food group balance, veggie density, health score) - NOT macro counting.
4. **Manage their budget** and flag when they're approaching limits.

## Your Personality
- Warm and conversational, like a friend who's great at meal planning
- Proactive about suggesting healthier swaps and sale items
- Practical and budget-conscious
- You explain WHY you suggest things (e.g., "pears are in season and on sale, plus they're great in salads")

## Key Behaviors
- When discussing dietary needs, ask about allergies, preferences (vegan, low-carb, etc.), household size, and budget
- When building a list, organize by category (produce, protein, dairy, pantry, etc.)
- Always note when items are on sale or when there's a cheaper alternative
- Suggest complete meal ideas, not just individual ingredients
- Flag when the cart is getting unbalanced nutritionally (too many processed items, not enough veggies)
- When suggesting substitutions for sale items, explain the comparison: "Why not pears instead of apples? They're $1.50/lb vs $2.99/lb and equally nutritious"

## Tool Usage
You have access to tools to:
- Manage the grocery list (add/remove items, save/load lists)
- Search Walmart for products and prices
- Add items to the Walmart cart via browser
- Check nutrition scores
- Track budget

Use these tools when the user wants to take action. For planning and discussion, just converse naturally.

## Important
- Never recommend specific medical diets without suggesting they consult a doctor
- Focus on general healthy eating principles
- Be honest about price comparisons - only flag real savings
- If you're unsure about an item's availability, say so
"""

# Tool definitions for Claude's tool use
TOOLS = [
    {
        "name": "add_to_grocery_list",
        "description": "Add an item to the current grocery list. Use this when the user agrees to add something.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the grocery item (e.g., 'organic chicken breast')",
                },
                "quantity": {
                    "type": "integer",
                    "description": "Number of units to buy",
                    "default": 1,
                },
                "unit": {
                    "type": "string",
                    "description": "Unit of measurement (e.g., 'lbs', 'oz', 'bunch')",
                    "default": "",
                },
                "notes": {
                    "type": "string",
                    "description": "Any notes about the item",
                    "default": "",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "remove_from_grocery_list",
        "description": "Remove an item from the grocery list by its name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_name": {
                    "type": "string",
                    "description": "Name of the item to remove",
                },
            },
            "required": ["item_name"],
        },
    },
    {
        "name": "show_grocery_list",
        "description": "Display the current grocery list with all items.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "search_walmart",
        "description": "Search for a product on Walmart to check prices and availability. Returns product names, prices, and sale status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., 'organic apples')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "compare_prices",
        "description": "Search for an item and its alternatives to find the best deal. Great for finding sale substitutions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {
                    "type": "string",
                    "description": "Primary item to search for",
                },
                "alternatives": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Alternative items to compare (e.g., ['pears', 'plums'] when searching for apples)",
                },
            },
            "required": ["item"],
        },
    },
    {
        "name": "add_to_walmart_cart",
        "description": "Add a specific product to the Walmart cart via browser automation. Use after searching and confirming with the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_index": {
                    "type": "integer",
                    "description": "Index of the product from search results to add (0-based)",
                    "default": 0,
                },
                "search_query": {
                    "type": "string",
                    "description": "Search query to find the product first",
                },
            },
            "required": ["search_query"],
        },
    },
    {
        "name": "check_nutrition",
        "description": "Get a nutrition/health score for the current grocery list.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "check_budget",
        "description": "Check current budget status - total spent, remaining, and warnings.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "set_budget",
        "description": "Set a budget for this shopping session.",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {
                    "type": "number",
                    "description": "Budget amount in dollars",
                },
            },
            "required": ["amount"],
        },
    },
    {
        "name": "save_list",
        "description": "Save the current grocery list for future reuse.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the saved list (e.g., 'weekly_essentials')",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "load_saved_list",
        "description": "Load a previously saved grocery list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the saved list to load",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "show_saved_lists",
        "description": "Show all saved grocery lists.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_cart_total",
        "description": "Check the current Walmart cart total from the browser.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "create_meal_plan",
        "description": "Generate a grocery list based on a meal plan. The LLM will suggest meals and corresponding ingredients.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to plan for",
                    "default": 7,
                },
                "people": {
                    "type": "integer",
                    "description": "Number of people to cook for",
                    "default": 2,
                },
                "preferences": {
                    "type": "string",
                    "description": "Dietary preferences or restrictions",
                    "default": "",
                },
                "budget": {
                    "type": "number",
                    "description": "Budget for the meal plan",
                    "default": 0,
                },
            },
            "required": ["days"],
        },
    },
    {
        "name": "start_shopping",
        "description": "Begin the shopping process - search for each item on the grocery list on Walmart and add them to cart one by one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "check_sales": {
                    "type": "boolean",
                    "description": "Whether to check for sale alternatives for each item",
                    "default": True,
                },
            },
            "required": [],
        },
    },
    {
        "name": "spending_history",
        "description": "Show past shopping session spending history.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


class GroceryLLM:
    """LLM-powered conversational grocery assistant."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        # Accept ANTHROPIC_API_KEY or ANTHROPIC_API as the env var name
        api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API")
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model
        self.messages: list[dict] = []
        self._tool_handler: Optional[Any] = None

    def set_tool_handler(self, handler: Any) -> None:
        """Set the callback handler for tool execution.

        The handler should be an object with methods matching tool names.
        """
        self._tool_handler = handler

    async def chat(self, user_message: str) -> str:
        """Send a message and get a response, handling tool calls.

        Args:
            user_message: The user's natural language input

        Returns:
            The assistant's text response
        """
        self.messages.append({"role": "user", "content": user_message})

        # Keep conversation manageable
        if len(self.messages) > 100:
            self.messages = self.messages[-60:]

        return await self._get_response()

    async def _get_response(self) -> str:
        """Get a response from Claude, handling tool use loops."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=self.messages,
        )

        # Process the response - may involve multiple tool calls
        full_text = ""

        while response.stop_reason == "tool_use":
            # Collect all content blocks
            assistant_content = response.content
            self.messages.append({"role": "assistant", "content": assistant_content})

            # Extract text parts
            for block in assistant_content:
                if block.type == "text":
                    full_text += block.text

            # Process tool calls
            tool_results = []
            for block in assistant_content:
                if block.type == "tool_use":
                    result = await self._execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result) if isinstance(result, dict) else str(result),
                    })

            self.messages.append({"role": "user", "content": tool_results})

            # Get next response
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.messages,
            )

        # Final text response
        final_content = response.content
        self.messages.append({"role": "assistant", "content": final_content})

        for block in final_content:
            if block.type == "text":
                full_text += block.text

        return full_text

    async def _execute_tool(self, tool_name: str, tool_input: dict) -> Any:
        """Execute a tool call by delegating to the handler."""
        if not self._tool_handler:
            return {"error": "No tool handler configured"}

        handler_method = getattr(self._tool_handler, f"handle_{tool_name}", None)
        if handler_method:
            try:
                result = await handler_method(**tool_input)
                logger.info(f"Tool {tool_name} executed successfully")
                return result
            except Exception as e:
                logger.error(f"Tool {tool_name} failed: {e}")
                return {"error": str(e)}
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    def get_conversation_summary(self) -> str:
        """Get a summary of the conversation for context."""
        user_msgs = [
            m["content"]
            for m in self.messages
            if m["role"] == "user" and isinstance(m["content"], str)
        ]
        return f"Conversation with {len(user_msgs)} user messages"
