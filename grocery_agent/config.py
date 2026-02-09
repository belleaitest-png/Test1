"""Configuration and persistent storage for the grocery agent."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "saved_lists"
BUDGET_FILE = DATA_DIR / "budget_history.json"
LISTS_DIR = DATA_DIR

# Ensure data directory exists
DATA_DIR.mkdir(exist_ok=True)

# Browser settings
WALMART_GROCERY_URL = "https://www.walmart.com/browse/food/976759"
WALMART_SEARCH_URL = "https://www.walmart.com/search?q={query}&cat_id=976759"
WALMART_CART_URL = "https://www.walmart.com/cart"
WALMART_HOME_URL = "https://www.walmart.com"

# Timeouts (milliseconds)
PAGE_LOAD_TIMEOUT = 30000
ELEMENT_TIMEOUT = 10000
SEARCH_RESULT_TIMEOUT = 15000

# LLM settings
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
MAX_CONVERSATION_HISTORY = 50

# Nutrition category mappings (keywords -> category)
NUTRITION_KEYWORDS: dict[str, str] = {
    # Vegetables
    "broccoli": "vegetable", "spinach": "vegetable", "kale": "vegetable",
    "carrot": "vegetable", "tomato": "vegetable", "pepper": "vegetable",
    "onion": "vegetable", "garlic": "vegetable", "lettuce": "vegetable",
    "cucumber": "vegetable", "zucchini": "vegetable", "celery": "vegetable",
    "cauliflower": "vegetable", "asparagus": "vegetable", "mushroom": "vegetable",
    "potato": "vegetable", "sweet potato": "vegetable", "corn": "vegetable",
    "peas": "vegetable", "green bean": "vegetable", "cabbage": "vegetable",
    "salad": "vegetable", "avocado": "vegetable",
    # Fruits
    "apple": "fruit", "banana": "fruit", "orange": "fruit", "grape": "fruit",
    "strawberry": "fruit", "blueberry": "fruit", "raspberry": "fruit",
    "mango": "fruit", "pineapple": "fruit", "watermelon": "fruit",
    "pear": "fruit", "peach": "fruit", "lemon": "fruit", "lime": "fruit",
    "cherry": "fruit", "berry": "fruit", "melon": "fruit", "kiwi": "fruit",
    # Proteins
    "chicken": "protein", "beef": "protein", "pork": "protein", "turkey": "protein",
    "salmon": "protein", "tuna": "protein", "shrimp": "protein", "fish": "protein",
    "egg": "protein", "tofu": "protein", "tempeh": "protein", "steak": "protein",
    "ground meat": "protein", "sausage": "protein", "bacon": "protein",
    # Dairy
    "milk": "dairy", "cheese": "dairy", "yogurt": "dairy", "butter": "dairy",
    "cream": "dairy", "cottage cheese": "dairy", "sour cream": "dairy",
    # Grains
    "bread": "grain", "rice": "grain", "pasta": "grain", "oat": "grain",
    "quinoa": "grain", "cereal": "grain", "tortilla": "grain", "flour": "grain",
    "bagel": "grain", "noodle": "grain", "couscous": "grain",
    # Legumes
    "bean": "legume", "lentil": "legume", "chickpea": "legume",
    "hummus": "legume", "black bean": "legume", "kidney bean": "legume",
    # Nuts & Seeds
    "almond": "nut_seed", "walnut": "nut_seed", "cashew": "nut_seed",
    "peanut": "nut_seed", "sunflower seed": "nut_seed", "chia": "nut_seed",
    "flax": "nut_seed", "pistachio": "nut_seed", "pecan": "nut_seed",
    # Healthy fats
    "olive oil": "healthy_fat", "coconut oil": "healthy_fat",
    "avocado oil": "healthy_fat",
    # Processed
    "chip": "processed", "cookie": "processed", "candy": "processed",
    "soda": "processed", "frozen pizza": "processed", "hot dog": "processed",
    "instant noodle": "processed", "ramen": "processed",
    # Snacks
    "cracker": "snack", "granola bar": "snack", "trail mix": "snack",
    "popcorn": "snack", "pretzel": "snack",
    # Beverages
    "juice": "beverage", "coffee": "beverage", "tea": "beverage",
    "water": "beverage", "kombucha": "beverage",
    # Condiments
    "sauce": "condiment", "ketchup": "condiment", "mustard": "condiment",
    "mayonnaise": "condiment", "dressing": "condiment", "vinegar": "condiment",
    "soy sauce": "condiment", "hot sauce": "condiment", "salsa": "condiment",
    "honey": "condiment", "maple syrup": "condiment", "jam": "condiment",
}


def save_list_to_file(grocery_list: dict, filename: str | None = None) -> Path:
    """Save a grocery list to a JSON file."""
    if filename is None:
        safe_name = grocery_list.get("name", "unnamed").replace(" ", "_").lower()
        filename = f"{safe_name}.json"
    filepath = LISTS_DIR / filename
    grocery_list["saved_at"] = datetime.now().isoformat()
    with open(filepath, "w") as f:
        json.dump(grocery_list, f, indent=2, default=str)
    return filepath


def load_list_from_file(filename: str) -> dict | None:
    """Load a grocery list from a JSON file."""
    filepath = LISTS_DIR / filename
    if not filepath.exists():
        return None
    with open(filepath) as f:
        return json.load(f)


def get_saved_lists() -> list[str]:
    """Return names of all saved grocery lists."""
    return [f.stem for f in LISTS_DIR.glob("*.json") if f.name != "budget_history.json"]


def save_budget_entry(entry: dict) -> None:
    """Append a budget entry to history."""
    history = load_budget_history()
    entry["timestamp"] = datetime.now().isoformat()
    history.append(entry)
    with open(BUDGET_FILE, "w") as f:
        json.dump(history, f, indent=2, default=str)


def load_budget_history() -> list[dict]:
    """Load budget history."""
    if not BUDGET_FILE.exists():
        return []
    with open(BUDGET_FILE) as f:
        return json.load(f)
