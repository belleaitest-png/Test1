"""Kroger API client for product search, store locations, and cart management.

Replaces browser-based Walmart scraping with clean API calls.
Register for free API credentials at https://developer.kroger.com
"""

from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any, Optional

import httpx

from grocery_agent.models import KrogerProduct

logger = logging.getLogger(__name__)

KROGER_BASE_URL = "https://api.kroger.com/v1"
KROGER_TOKEN_URL = f"{KROGER_BASE_URL}/connect/oauth2/token"
KROGER_PRODUCTS_URL = f"{KROGER_BASE_URL}/products"
KROGER_LOCATIONS_URL = f"{KROGER_BASE_URL}/locations"
KROGER_CART_URL = f"{KROGER_BASE_URL}/cart/add"


class KrogerClient:
    """HTTP client for the Kroger public API.

    Auth flow:
        1. Register at https://developer.kroger.com
        2. Set KROGER_CLIENT_ID and KROGER_CLIENT_SECRET env vars
        3. The client handles OAuth2 token management automatically
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        location_id: str | None = None,
    ) -> None:
        self.client_id = client_id or os.environ.get("KROGER_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("KROGER_CLIENT_SECRET", "")
        self.location_id = location_id
        self._access_token: str | None = None
        self._token_expires_at: float = 0
        self._http = httpx.Client(timeout=15)

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _get_basic_auth(self) -> str:
        """Encode client credentials for OAuth2 Basic auth."""
        creds = f"{self.client_id}:{self.client_secret}"
        return base64.b64encode(creds.encode()).decode()

    def _ensure_token(self) -> None:
        """Obtain or refresh the OAuth2 access token."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return  # token still valid (with 60s buffer)

        if not self.is_configured:
            raise RuntimeError(
                "Kroger API credentials not set. "
                "Set KROGER_CLIENT_ID and KROGER_CLIENT_SECRET env vars, "
                "or register at https://developer.kroger.com"
            )

        resp = self._http.post(
            KROGER_TOKEN_URL,
            headers={
                "Authorization": f"Basic {self._get_basic_auth()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "product.compact",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 1800)
        logger.info("Kroger OAuth2 token obtained")

    def _authed_headers(self) -> dict[str, str]:
        self._ensure_token()
        return {"Authorization": f"Bearer {self._access_token}"}

    # ── Locations ──────────────────────────────────────────────

    def search_locations(
        self,
        zip_code: str,
        radius_miles: int = 10,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Find nearby Kroger-family stores by zip code.

        Returns list of dicts with locationId, name, address, etc.
        """
        self._ensure_token()
        resp = self._http.get(
            KROGER_LOCATIONS_URL,
            headers=self._authed_headers(),
            params={
                "filter.zipCode.near": zip_code,
                "filter.radiusInMiles": radius_miles,
                "filter.limit": limit,
            },
        )
        resp.raise_for_status()
        stores = resp.json().get("data", [])
        results = []
        for s in stores:
            addr = s.get("address", {})
            results.append({
                "locationId": s["locationId"],
                "name": s.get("name", ""),
                "chain": s.get("chain", ""),
                "address": (
                    f"{addr.get('addressLine1', '')}, "
                    f"{addr.get('city', '')} {addr.get('state', '')} "
                    f"{addr.get('zipCode', '')}"
                ),
            })
        logger.info(f"Found {len(results)} stores near {zip_code}")
        return results

    def set_location(self, location_id: str) -> None:
        """Set the store location for price lookups."""
        self.location_id = location_id
        logger.info(f"Store location set to {location_id}")

    # ── Products ───────────────────────────────────────────────

    def search_products(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[KrogerProduct]:
        """Search for grocery products at the selected store.

        Args:
            query: Search terms (e.g., "organic chicken breast")
            max_results: Max products to return (1-50)

        Returns:
            List of KrogerProduct with price and availability info
        """
        self._ensure_token()
        params: dict[str, Any] = {
            "filter.term": query,
            "filter.limit": min(max_results, 50),
        }
        if self.location_id:
            params["filter.locationId"] = self.location_id

        resp = self._http.get(
            KROGER_PRODUCTS_URL,
            headers=self._authed_headers(),
            params=params,
        )
        resp.raise_for_status()

        products: list[KrogerProduct] = []
        for item in resp.json().get("data", []):
            product = self._parse_product(item)
            if product:
                products.append(product)

        logger.info(f"Found {len(products)} products for '{query}'")
        return products

    def _parse_product(self, data: dict) -> KrogerProduct | None:
        """Parse a single product from the Kroger API response."""
        try:
            name = data.get("description", "")
            product_id = data.get("productId", "")
            brand = data.get("brand", "")
            upc = data.get("upc", "")

            # Price info (requires location)
            price = 0.0
            promo_price: float | None = None
            on_sale = False
            items = data.get("items", [])
            if items:
                item = items[0]
                price_info = item.get("price", {})
                price = price_info.get("regular", 0.0)
                promo = price_info.get("promo", 0.0)
                if promo and promo > 0 and promo < price:
                    promo_price = promo
                    on_sale = True

                # Check stock
                in_stock = item.get("fulfillment", {}).get("inStore", True)
            else:
                in_stock = True

            # Image
            images = data.get("images", [])
            image_url = ""
            for img_group in images:
                for size in img_group.get("sizes", []):
                    if size.get("size") == "medium":
                        image_url = size.get("url", "")
                        break
                if image_url:
                    break

            if not name:
                return None

            return KrogerProduct(
                product_id=product_id,
                upc=upc,
                name=name,
                brand=brand,
                price=price,
                promo_price=promo_price,
                on_sale=on_sale,
                in_stock=in_stock,
                image_url=image_url,
            )
        except Exception as e:
            logger.warning(f"Failed to parse product: {e}")
            return None

    def compare_products(
        self,
        query: str,
        alternatives: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search for an item and alternatives, comparing prices.

        Returns dict with primary results, alternative results, and best deal.
        """
        primary = self.search_products(query, max_results=5)

        result: dict[str, Any] = {
            "primary_item": query,
            "primary_results": primary,
            "alternatives": {},
            "best_deal": None,
            "sale_items": [],
        }

        if alternatives:
            for alt in alternatives:
                alt_results = self.search_products(alt, max_results=5)
                result["alternatives"][alt] = alt_results
                for p in alt_results:
                    if p.on_sale:
                        result["sale_items"].append({
                            "item": alt,
                            "product": p,
                            "suggestion": (
                                f"Consider {alt} instead of {query} — "
                                f"{p.name} is on sale at {p.display_price()}"
                            ),
                        })

        # Find best deal across all results
        all_products = list(primary)
        for alt_results in result["alternatives"].values():
            all_products.extend(alt_results)

        if all_products:
            on_sale = [p for p in all_products if p.on_sale]
            if on_sale:
                result["best_deal"] = min(on_sale, key=lambda p: p.effective_price)
            else:
                in_stock = [p for p in all_products if p.in_stock and p.price > 0]
                if in_stock:
                    result["best_deal"] = min(in_stock, key=lambda p: p.price)

        return result

    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()
