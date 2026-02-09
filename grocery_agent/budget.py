"""Budget tracking for grocery shopping sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from grocery_agent.config import load_budget_history, save_budget_entry
from grocery_agent.models import CartItem, ShoppingSession


class BudgetTracker:
    """Tracks spending during a shopping session and across history."""

    def __init__(self, budget: Optional[float] = None) -> None:
        self.budget = budget
        self._items: list[CartItem] = []
        self._started_at = datetime.now()

    def set_budget(self, amount: float) -> None:
        """Set or update the session budget."""
        self.budget = amount

    def add_item(self, item: CartItem) -> dict:
        """Record an item added to cart. Returns budget status."""
        self._items.append(item)
        return self.status()

    def remove_item(self, item_id: str) -> bool:
        """Remove an item from tracking."""
        for i, item in enumerate(self._items):
            if item.grocery_item.id == item_id:
                self._items.pop(i)
                return True
        return False

    @property
    def total_spent(self) -> float:
        return sum(i.total_price for i in self._items)

    @property
    def remaining(self) -> Optional[float]:
        if self.budget is not None:
            return self.budget - self.total_spent
        return None

    @property
    def item_count(self) -> int:
        return len(self._items)

    def status(self) -> dict:
        """Get current budget status."""
        result = {
            "total_spent": self.total_spent,
            "item_count": self.item_count,
            "budget": self.budget,
            "remaining": self.remaining,
            "over_budget": False,
            "warning": None,
        }

        if self.budget is not None:
            remaining = self.remaining
            if remaining is not None and remaining < 0:
                result["over_budget"] = True
                result["warning"] = (
                    f"Over budget by ${abs(remaining):.2f}! "
                    f"(Budget: ${self.budget:.2f}, Spent: ${self.total_spent:.2f})"
                )
            elif remaining is not None and remaining < self.budget * 0.1:
                result["warning"] = (
                    f"Approaching budget limit! "
                    f"Only ${remaining:.2f} remaining of ${self.budget:.2f}"
                )

        return result

    def format_status(self) -> str:
        """Format budget status for display."""
        s = self.status()
        lines = [
            f"Cart Total: ${s['total_spent']:.2f} ({s['item_count']} items)",
        ]
        if s["budget"] is not None:
            lines.append(f"Budget: ${s['budget']:.2f}")
            lines.append(f"Remaining: ${s['remaining']:.2f}")
            pct = (s["total_spent"] / s["budget"] * 100) if s["budget"] > 0 else 0
            bar_len = 30
            filled = int(bar_len * min(pct, 100) / 100)
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.append(f"[{bar}] {pct:.0f}%")
        if s["warning"]:
            lines.append(f"⚠ {s['warning']}")
        return "\n".join(lines)

    def save_session(self) -> None:
        """Save this session's spending to history."""
        entry = {
            "date": self._started_at.isoformat(),
            "total_spent": self.total_spent,
            "item_count": self.item_count,
            "budget": self.budget,
            "items": [
                {
                    "name": i.grocery_item.name,
                    "price": i.walmart_product.price,
                    "quantity": i.quantity,
                }
                for i in self._items
            ],
        }
        save_budget_entry(entry)

    @staticmethod
    def get_spending_history() -> str:
        """Format spending history for display."""
        history = load_budget_history()
        if not history:
            return "No shopping history yet."

        lines = ["=== Shopping History ==="]
        total_all_time = 0
        for entry in history[-10:]:  # Last 10 sessions
            date = entry.get("date", "Unknown")[:10]
            total = entry.get("total_spent", 0)
            items = entry.get("item_count", 0)
            budget = entry.get("budget")
            total_all_time += total

            line = f"  {date}: ${total:.2f} ({items} items)"
            if budget:
                line += f" [budget: ${budget:.2f}]"
            lines.append(line)

        lines.append(f"\nTotal all-time: ${total_all_time:.2f}")
        lines.append(f"Sessions: {len(history)}")
        if history:
            avg = total_all_time / len(history)
            lines.append(f"Average per trip: ${avg:.2f}")

        return "\n".join(lines)
