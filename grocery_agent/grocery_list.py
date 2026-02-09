"""Grocery list management with persistence."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from grocery_agent.config import (
    LISTS_DIR,
    get_saved_lists,
    load_list_from_file,
    save_list_to_file,
)
from grocery_agent.models import GroceryItem, GroceryList, NutritionCategory, HealthTier
from grocery_agent.nutrition import classify_item


class GroceryListManager:
    """Manages grocery lists with save/load and classification."""

    def __init__(self) -> None:
        self._lists: dict[str, GroceryList] = {}
        self._active_list: Optional[str] = None

    @property
    def active_list(self) -> Optional[GroceryList]:
        if self._active_list and self._active_list in self._lists:
            return self._lists[self._active_list]
        return None

    def create_list(
        self, name: str, dietary_notes: str = ""
    ) -> GroceryList:
        """Create a new grocery list."""
        gl = GroceryList(name=name, dietary_notes=dietary_notes)
        self._lists[gl.id] = gl
        self._active_list = gl.id
        return gl

    def add_item(
        self,
        name: str,
        quantity: int = 1,
        unit: str = "",
        notes: str = "",
        list_id: Optional[str] = None,
    ) -> GroceryItem:
        """Add an item to a list (default: active list).

        Automatically classifies the item by nutrition category.
        """
        target_id = list_id or self._active_list
        if not target_id or target_id not in self._lists:
            raise ValueError("No active list. Create a list first.")

        category, health_tier = classify_item(name)
        item = GroceryItem(
            name=name,
            quantity=quantity,
            unit=unit,
            category=category,
            health_tier=health_tier,
            notes=notes,
        )
        self._lists[target_id].add_item(item)
        return item

    def remove_item(self, item_id: str, list_id: Optional[str] = None) -> bool:
        """Remove an item from a list."""
        target_id = list_id or self._active_list
        if not target_id or target_id not in self._lists:
            return False
        return self._lists[target_id].remove_item(item_id)

    def get_items(self, list_id: Optional[str] = None) -> list[GroceryItem]:
        """Get all items from a list."""
        target_id = list_id or self._active_list
        if not target_id or target_id not in self._lists:
            return []
        return self._lists[target_id].items

    def display_list(self, list_id: Optional[str] = None) -> str:
        """Get a formatted display of a list."""
        target_id = list_id or self._active_list
        if not target_id or target_id not in self._lists:
            return "No active list."
        return self._lists[target_id].display()

    def save_list(self, list_id: Optional[str] = None) -> str:
        """Save a list to disk. Returns the file path."""
        target_id = list_id or self._active_list
        if not target_id or target_id not in self._lists:
            raise ValueError("No list to save.")

        gl = self._lists[target_id]
        data = {
            "id": gl.id,
            "name": gl.name,
            "dietary_notes": gl.dietary_notes,
            "created_at": gl.created_at.isoformat(),
            "items": [
                {
                    "id": item.id,
                    "name": item.name,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "category": item.category.value,
                    "health_tier": item.health_tier.value,
                    "notes": item.notes,
                }
                for item in gl.items
            ],
        }
        path = save_list_to_file(data)
        return str(path)

    def load_list(self, name: str) -> Optional[GroceryList]:
        """Load a saved list by name."""
        data = load_list_from_file(f"{name}.json")
        if not data:
            return None

        gl = GroceryList(
            name=data["name"],
            dietary_notes=data.get("dietary_notes", ""),
            id=data.get("id", ""),
        )

        for item_data in data.get("items", []):
            try:
                cat = NutritionCategory(item_data.get("category", "other"))
            except ValueError:
                cat = NutritionCategory.OTHER
            try:
                tier = HealthTier(item_data.get("health_tier", "moderate"))
            except ValueError:
                tier = HealthTier.MODERATE

            item = GroceryItem(
                name=item_data["name"],
                quantity=item_data.get("quantity", 1),
                unit=item_data.get("unit", ""),
                category=cat,
                health_tier=tier,
                notes=item_data.get("notes", ""),
                id=item_data.get("id", ""),
            )
            gl.add_item(item)

        self._lists[gl.id] = gl
        self._active_list = gl.id
        return gl

    def list_saved(self) -> list[str]:
        """Return names of all saved lists."""
        return get_saved_lists()

    def get_all_lists(self) -> dict[str, GroceryList]:
        """Return all in-memory lists."""
        return self._lists

    def set_active(self, list_id: str) -> bool:
        """Set the active list by ID."""
        if list_id in self._lists:
            self._active_list = list_id
            return True
        return False

    def items_as_search_queries(self, list_id: Optional[str] = None) -> list[str]:
        """Convert list items to Walmart search queries."""
        items = self.get_items(list_id)
        queries = []
        for item in items:
            query = item.name
            if item.unit:
                query = f"{item.unit} {item.name}"
            queries.append(query)
        return queries
