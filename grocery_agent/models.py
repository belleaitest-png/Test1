"""Data models for the grocery shopping agent."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class NutritionCategory(Enum):
    """Broad nutrition categories for health scoring."""
    VEGETABLE = "vegetable"
    FRUIT = "fruit"
    PROTEIN = "protein"
    DAIRY = "dairy"
    GRAIN = "grain"
    LEGUME = "legume"
    NUT_SEED = "nut_seed"
    HEALTHY_FAT = "healthy_fat"
    PROCESSED = "processed"
    SNACK = "snack"
    BEVERAGE = "beverage"
    CONDIMENT = "condiment"
    FROZEN = "frozen"
    OTHER = "other"


class HealthTier(Enum):
    """Simple health tier for items and overall basket."""
    EXCELLENT = "excellent"   # Whole foods, vegetables, fruits
    GOOD = "good"             # Lean proteins, whole grains, legumes
    MODERATE = "moderate"     # Dairy, some processed items
    LOW = "low"               # Highly processed, sugary items


@dataclass
class GroceryItem:
    """A single grocery item."""
    name: str
    quantity: int = 1
    unit: str = ""
    category: NutritionCategory = NutritionCategory.OTHER
    health_tier: HealthTier = HealthTier.MODERATE
    notes: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def display(self) -> str:
        qty = f"{self.quantity}" if self.quantity > 1 else ""
        unit = f" {self.unit}" if self.unit else ""
        return f"{qty}{unit} {self.name}".strip()


@dataclass
class WalmartProduct:
    """A product found on Walmart's website."""
    name: str
    price: float
    unit_price: str = ""
    image_url: str = ""
    product_url: str = ""
    on_sale: bool = False
    original_price: Optional[float] = None
    sale_badge: str = ""
    in_stock: bool = True
    seller: str = "Walmart"

    @property
    def discount_pct(self) -> Optional[float]:
        if self.on_sale and self.original_price and self.original_price > 0:
            return round((1 - self.price / self.original_price) * 100, 1)
        return None

    def display(self) -> str:
        price_str = f"${self.price:.2f}"
        if self.on_sale and self.original_price:
            price_str = f"${self.price:.2f} (was ${self.original_price:.2f}, {self.discount_pct}% off)"
        if self.sale_badge:
            price_str += f" [{self.sale_badge}]"
        return f"{self.name} - {price_str}"


@dataclass
class CartItem:
    """An item added to the Walmart cart."""
    grocery_item: GroceryItem
    walmart_product: WalmartProduct
    quantity: int = 1
    added_at: datetime = field(default_factory=datetime.now)

    @property
    def total_price(self) -> float:
        return self.walmart_product.price * self.quantity


@dataclass
class GroceryList:
    """A named grocery list that can be saved and reloaded."""
    name: str
    items: list[GroceryItem] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    dietary_notes: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def add_item(self, item: GroceryItem) -> None:
        self.items.append(item)
        self.updated_at = datetime.now()

    def remove_item(self, item_id: str) -> bool:
        for i, item in enumerate(self.items):
            if item.id == item_id:
                self.items.pop(i)
                self.updated_at = datetime.now()
                return True
        return False

    def display(self) -> str:
        lines = [f"=== {self.name} ({len(self.items)} items) ==="]
        if self.dietary_notes:
            lines.append(f"Diet: {self.dietary_notes}")
        for item in self.items:
            lines.append(f"  - {item.display()}")
        return "\n".join(lines)


@dataclass
class ShoppingSession:
    """Tracks a single shopping session."""
    cart_items: list[CartItem] = field(default_factory=list)
    budget: Optional[float] = None
    started_at: datetime = field(default_factory=datetime.now)
    sale_suggestions: list[dict] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return sum(item.total_price for item in self.cart_items)

    @property
    def budget_remaining(self) -> Optional[float]:
        if self.budget is not None:
            return self.budget - self.total_cost
        return None

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.cart_items)


@dataclass
class NutritionScore:
    """Overall nutrition score for a grocery list or cart."""
    total_items: int = 0
    veg_fruit_count: int = 0
    protein_count: int = 0
    whole_grain_count: int = 0
    processed_count: int = 0
    health_score: float = 0.0  # 0-100
    tier: HealthTier = HealthTier.MODERATE
    suggestions: list[str] = field(default_factory=list)

    def display(self) -> str:
        lines = [
            f"Health Score: {self.health_score:.0f}/100 ({self.tier.value})",
            f"  Fruits & Vegetables: {self.veg_fruit_count}/{self.total_items}",
            f"  Proteins: {self.protein_count}/{self.total_items}",
            f"  Whole Grains: {self.whole_grain_count}/{self.total_items}",
            f"  Processed Items: {self.processed_count}/{self.total_items}",
        ]
        if self.suggestions:
            lines.append("  Suggestions:")
            for s in self.suggestions:
                lines.append(f"    - {s}")
        return "\n".join(lines)
