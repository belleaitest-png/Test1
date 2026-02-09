"""Nutrition scoring system.

Provides a general health score for grocery lists and carts,
focusing on food group balance rather than macro counting.
"""

from __future__ import annotations

from grocery_agent.config import NUTRITION_KEYWORDS
from grocery_agent.models import (
    GroceryItem,
    HealthTier,
    NutritionCategory,
    NutritionScore,
)


# Health tier mappings
CATEGORY_HEALTH_TIERS: dict[NutritionCategory, HealthTier] = {
    NutritionCategory.VEGETABLE: HealthTier.EXCELLENT,
    NutritionCategory.FRUIT: HealthTier.EXCELLENT,
    NutritionCategory.LEGUME: HealthTier.EXCELLENT,
    NutritionCategory.NUT_SEED: HealthTier.GOOD,
    NutritionCategory.HEALTHY_FAT: HealthTier.GOOD,
    NutritionCategory.PROTEIN: HealthTier.GOOD,
    NutritionCategory.GRAIN: HealthTier.GOOD,
    NutritionCategory.DAIRY: HealthTier.MODERATE,
    NutritionCategory.BEVERAGE: HealthTier.MODERATE,
    NutritionCategory.CONDIMENT: HealthTier.MODERATE,
    NutritionCategory.FROZEN: HealthTier.MODERATE,
    NutritionCategory.SNACK: HealthTier.MODERATE,
    NutritionCategory.OTHER: HealthTier.MODERATE,
    NutritionCategory.PROCESSED: HealthTier.LOW,
}

# Points for health score calculation (out of 100)
TIER_POINTS: dict[HealthTier, float] = {
    HealthTier.EXCELLENT: 100,
    HealthTier.GOOD: 75,
    HealthTier.MODERATE: 50,
    HealthTier.LOW: 20,
}

# Ideal food group ratios (as percentage of total items)
IDEAL_RATIOS = {
    "veg_fruit": 0.35,     # 35% fruits and vegetables
    "protein": 0.20,       # 20% protein sources
    "grain": 0.15,         # 15% whole grains
    "dairy": 0.10,         # 10% dairy
    "legume_nut": 0.10,    # 10% legumes, nuts, seeds
    "other": 0.10,         # 10% other (condiments, beverages, etc.)
}


def classify_item(item_name: str) -> tuple[NutritionCategory, HealthTier]:
    """Classify a grocery item by nutrition category and health tier.

    Uses keyword matching against the item name.
    """
    name_lower = item_name.lower()

    # Check for keyword matches (longest match first for accuracy)
    sorted_keywords = sorted(NUTRITION_KEYWORDS.keys(), key=len, reverse=True)

    for keyword in sorted_keywords:
        if keyword in name_lower:
            category_str = NUTRITION_KEYWORDS[keyword]
            category = NutritionCategory(category_str)
            tier = CATEGORY_HEALTH_TIERS.get(category, HealthTier.MODERATE)
            return category, tier

    # Check for "organic" prefix boost - still need to classify
    if "organic" in name_lower:
        # Organic items get a slight health boost but we still need category
        return NutritionCategory.OTHER, HealthTier.GOOD

    return NutritionCategory.OTHER, HealthTier.MODERATE


def score_items(items: list[GroceryItem]) -> NutritionScore:
    """Calculate a nutrition score for a list of grocery items.

    Scoring is based on:
    1. Food group balance (how close to ideal ratios)
    2. Health tier distribution (more excellent/good = higher score)
    3. Vegetable and fruit density
    """
    if not items:
        return NutritionScore()

    total = len(items)
    veg_fruit = 0
    protein = 0
    grain = 0
    dairy = 0
    legume_nut = 0
    processed = 0

    tier_counts = {tier: 0 for tier in HealthTier}

    for item in items:
        cat = item.category
        tier = item.health_tier
        tier_counts[tier] += 1

        if cat in (NutritionCategory.VEGETABLE, NutritionCategory.FRUIT):
            veg_fruit += 1
        elif cat == NutritionCategory.PROTEIN:
            protein += 1
        elif cat == NutritionCategory.GRAIN:
            grain += 1
        elif cat == NutritionCategory.DAIRY:
            dairy += 1
        elif cat in (NutritionCategory.LEGUME, NutritionCategory.NUT_SEED):
            legume_nut += 1
        elif cat == NutritionCategory.PROCESSED:
            processed += 1

    # Component 1: Health tier score (weighted average, 0-100)
    tier_score = sum(
        TIER_POINTS[tier] * count for tier, count in tier_counts.items()
    ) / total

    # Component 2: Veg/fruit density bonus (0-20 points)
    veg_ratio = veg_fruit / total
    veg_bonus = min(20, veg_ratio / IDEAL_RATIOS["veg_fruit"] * 20)

    # Component 3: Balance penalty (0-20 points deducted for imbalance)
    balance_penalty = 0
    if veg_fruit == 0:
        balance_penalty += 10
    if protein == 0 and total > 3:
        balance_penalty += 5
    if processed / total > 0.3:
        balance_penalty += 5

    # Final score
    raw_score = tier_score * 0.6 + veg_bonus + (20 - balance_penalty)
    health_score = max(0, min(100, raw_score))

    # Determine overall tier
    if health_score >= 80:
        overall_tier = HealthTier.EXCELLENT
    elif health_score >= 60:
        overall_tier = HealthTier.GOOD
    elif health_score >= 40:
        overall_tier = HealthTier.MODERATE
    else:
        overall_tier = HealthTier.LOW

    # Generate suggestions
    suggestions = _generate_suggestions(
        total, veg_fruit, protein, grain, processed, health_score
    )

    return NutritionScore(
        total_items=total,
        veg_fruit_count=veg_fruit,
        protein_count=protein,
        whole_grain_count=grain,
        processed_count=processed,
        health_score=health_score,
        tier=overall_tier,
        suggestions=suggestions,
    )


def _generate_suggestions(
    total: int,
    veg_fruit: int,
    protein: int,
    grain: int,
    processed: int,
    score: float,
) -> list[str]:
    """Generate actionable nutrition suggestions."""
    suggestions = []

    if total == 0:
        return ["Add some items to get nutrition suggestions!"]

    veg_ratio = veg_fruit / total
    if veg_ratio < 0.25:
        suggestions.append(
            "Add more fruits and vegetables - aim for at least 1/3 of your list"
        )
    elif veg_ratio >= 0.4:
        suggestions.append("Great fruit and vegetable balance!")

    if protein == 0 and total > 3:
        suggestions.append(
            "Consider adding a protein source (chicken, fish, tofu, beans)"
        )

    if grain == 0 and total > 5:
        suggestions.append(
            "Consider adding whole grains (brown rice, whole wheat bread, oats)"
        )

    processed_ratio = processed / total
    if processed_ratio > 0.3:
        suggestions.append(
            f"{processed} of {total} items are processed - try swapping some "
            "for whole food alternatives"
        )

    if score >= 80:
        suggestions.append("Excellent overall! Very healthy grocery selection.")
    elif score >= 60:
        suggestions.append("Good balance! A few tweaks could make it even healthier.")

    return suggestions


def format_health_summary(items: list[GroceryItem]) -> str:
    """Format a human-readable health summary for a grocery list."""
    score = score_items(items)
    return score.display()
