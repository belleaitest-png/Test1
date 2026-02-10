"""Walmart browser automation using Playwright.

Connects to the user's Chrome browser, searches for products,
scrapes prices/sales, and adds items to the cart.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from grocery_agent.config import (
    ELEMENT_TIMEOUT,
    PAGE_LOAD_TIMEOUT,
    SEARCH_RESULT_TIMEOUT,
    WALMART_CART_URL,
    WALMART_GROCERY_URL,
    WALMART_HOME_URL,
    WALMART_SEARCH_URL,
)
from grocery_agent.models import WalmartProduct

logger = logging.getLogger(__name__)


class WalmartBrowser:
    """Controls a Chrome browser to interact with Walmart's grocery section."""

    def __init__(
        self,
        headless: bool = True,
        cdp_url: Optional[str] = None,
    ) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._logged_in: bool = False
        self._headless: bool = headless
        self._cdp_url: Optional[str] = cdp_url

    async def launch(self) -> None:
        """Launch or connect to a Chrome browser.

        If a CDP URL was provided, connects to an existing Chrome instance
        (e.g. chrome://inspect or --remote-debugging-port). Otherwise
        launches a new Chromium browser.

        To use CDP, start Chrome with:
            google-chrome --remote-debugging-port=9222
        Then pass --cdp-url=http://localhost:9222 to the agent.
        """
        self._playwright = await async_playwright().start()

        if self._cdp_url:
            # Connect to an existing Chrome via Chrome DevTools Protocol
            self._browser = await self._playwright.chromium.connect_over_cdp(
                self._cdp_url, timeout=10000,
            )
            # Reuse the first existing context/page if available
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
                pages = self._context.pages
                if pages:
                    self._page = pages[0]
                else:
                    self._page = await self._context.new_page()
            else:
                self._context = await self._browser.new_context()
                self._page = await self._context.new_page()
            logger.info(f"Connected to existing browser via CDP: {self._cdp_url}")
        else:
            # Launch a new browser
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
            if not self._headless:
                launch_args.append("--start-maximized")
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
                args=launch_args,
            )
            self._context = await self._browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            self._page = await self._context.new_page()
            logger.info("Browser launched successfully")

    async def navigate_to_walmart(self) -> None:
        """Navigate to Walmart and wait for the user to log in."""
        if not self._page:
            raise RuntimeError("Browser not launched. Call launch() first.")
        timeout = PAGE_LOAD_TIMEOUT if not self._headless else 15000
        await self._page.goto(WALMART_HOME_URL, timeout=timeout)
        logger.info("Navigated to Walmart - waiting for user login")

    async def wait_for_login(self, timeout: int = 300) -> bool:
        """Wait for user to complete login. Returns True when logged in.

        Checks for account indicators on the page that show
        the user has successfully signed in.
        """
        if not self._page:
            return False

        print("\n[Browser] Please log in to your Walmart account in the browser window.")
        print("[Browser] I'll detect when you're logged in automatically...")
        print(f"[Browser] (Timeout: {timeout} seconds)\n")

        for _ in range(timeout):
            try:
                # Check for signed-in indicators
                signed_in = await self._page.evaluate("""() => {
                    // Check for account menu / signed in text
                    const accountBtn = document.querySelector(
                        '[data-automation-id="account-menu"], '
                        + '[aria-label*="Account"], '
                        + '.mw_icon_account'
                    );
                    const signInLink = document.querySelector(
                        'a[href*="/account/login"], '
                        + '[data-automation-id="sign-in"]'
                    );
                    // If account button exists and sign-in link doesn't,
                    // user is likely logged in
                    const bodyText = document.body?.innerText || '';
                    const hasHiUser = /Hi,\\s+\\w+/i.test(bodyText);
                    return hasHiUser || (accountBtn && !signInLink);
                }""")
                if signed_in:
                    self._logged_in = True
                    print("[Browser] Login detected! Ready to shop.")
                    return True
            except Exception:
                pass
            await asyncio.sleep(1)

        print("[Browser] Login timeout. You can continue manually.")
        return False

    async def search_products(self, query: str, max_results: int = 10) -> list[WalmartProduct]:
        """Search for grocery products on Walmart.

        Args:
            query: Search terms (e.g., "organic chicken breast")
            max_results: Maximum number of results to return

        Returns:
            List of WalmartProduct objects with price and sale info
        """
        if not self._page:
            raise RuntimeError("Browser not launched.")

        search_url = WALMART_SEARCH_URL.format(query=query.replace(" ", "+"))
        logger.info(f"Searching Walmart for: {query}")

        await self._page.goto(search_url, timeout=PAGE_LOAD_TIMEOUT)

        # Wait for search results to load
        try:
            await self._page.wait_for_selector(
                '[data-testid="list-view"] [data-item-id], '
                + '.search-result-gridview-item, '
                + '[data-testid="item-stack"] > div',
                timeout=SEARCH_RESULT_TIMEOUT,
            )
        except Exception:
            logger.warning("Search results may not have loaded fully")

        # Small delay for dynamic content
        await asyncio.sleep(2)

        # Extract product data from search results
        products_data = await self._page.evaluate("""(maxResults) => {
            const products = [];

            // Try multiple selector strategies for Walmart's layout
            const selectors = [
                '[data-testid="list-view"] [data-item-id]',
                '.search-result-gridview-item',
                '[data-testid="item-stack"] > div',
                '[data-testid="item-tile"]',
                '.mb1.ph1.pa0-xl.bb.b--near-white.w-25',
            ];

            let items = [];
            for (const sel of selectors) {
                items = document.querySelectorAll(sel);
                if (items.length > 0) break;
            }

            for (let i = 0; i < Math.min(items.length, maxResults); i++) {
                const item = items[i];
                const text = item.innerText || '';

                // Extract product name
                const nameEl = item.querySelector(
                    '[data-automation-id="product-title"], '
                    + 'a[link-identifier="linkText"] span, '
                    + '.lh-title span, '
                    + 'span[data-automation-id="product-title"]'
                );
                const name = nameEl?.textContent?.trim() || '';
                if (!name) continue;

                // Extract current price
                const priceEl = item.querySelector(
                    '[data-automation-id="product-price"] .f2, '
                    + '[itemprop="price"], '
                    + '.f2.f-headline-s, '
                    + 'div[data-automation-id="product-price"]'
                );
                let priceText = priceEl?.textContent || '';
                // Also try aria-label for price
                if (!priceText) {
                    const ariaPrice = item.querySelector('[aria-label*="current price"]');
                    priceText = ariaPrice?.getAttribute('aria-label') || '';
                }
                const priceMatch = priceText.match(/\\$?([\\d,]+\\.\\d{2})/);
                const price = priceMatch ? parseFloat(priceMatch[1].replace(',', '')) : 0;

                // Check for sale/rollback/clearance
                const saleIndicators = [
                    'Rollback', 'Was ', 'Save ', 'Clearance', 'Reduced',
                    'Price drop', 'Great Value'
                ];
                let onSale = false;
                let saleBadge = '';
                let originalPrice = null;

                for (const indicator of saleIndicators) {
                    if (text.includes(indicator)) {
                        onSale = true;
                        saleBadge = indicator;
                        break;
                    }
                }

                // Try to find original/was price
                const wasPriceMatch = text.match(/Was\\s*\\$([\\d,]+\\.\\d{2})/i);
                if (wasPriceMatch) {
                    originalPrice = parseFloat(wasPriceMatch[1].replace(',', ''));
                    onSale = true;
                }

                // Extract unit price
                const unitPriceEl = item.querySelector(
                    '.gray, .f7.f6-l, [data-automation-id="product-price"] + div'
                );
                const unitPrice = unitPriceEl?.textContent?.trim() || '';

                // Extract product link
                const linkEl = item.querySelector('a[href*="/ip/"]');
                const productUrl = linkEl ? linkEl.href : '';

                // Check stock
                const outOfStock = text.toLowerCase().includes('out of stock');

                if (price > 0) {
                    products.push({
                        name,
                        price,
                        unitPrice,
                        onSale,
                        originalPrice,
                        saleBadge,
                        productUrl,
                        inStock: !outOfStock,
                    });
                }
            }
            return products;
        }""", max_results)

        results = []
        for p in products_data:
            results.append(WalmartProduct(
                name=p["name"],
                price=p["price"],
                unit_price=p.get("unitPrice", ""),
                on_sale=p.get("onSale", False),
                original_price=p.get("originalPrice"),
                sale_badge=p.get("saleBadge", ""),
                product_url=p.get("productUrl", ""),
                in_stock=p.get("inStock", True),
            ))

        logger.info(f"Found {len(results)} products for '{query}'")
        return results

    async def add_to_cart(self, product: WalmartProduct) -> bool:
        """Navigate to a product page and add it to cart.

        Args:
            product: The WalmartProduct to add

        Returns:
            True if successfully added to cart
        """
        if not self._page or not product.product_url:
            return False

        try:
            await self._page.goto(product.product_url, timeout=PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(2)

            # Look for Add to Cart button
            add_btn_selectors = [
                '[data-automation-id="add-to-cart"] button',
                'button[data-testid="add-to-cart-btn"]',
                'button:has-text("Add to cart")',
                '[data-tl-id="ProductPrimaryCTA-normal"] button',
                'button.prod-ProductCTA--primary',
            ]

            for selector in add_btn_selectors:
                try:
                    btn = await self._page.wait_for_selector(
                        selector, timeout=3000
                    )
                    if btn:
                        await btn.click()
                        await asyncio.sleep(2)
                        logger.info(f"Added to cart: {product.name}")
                        return True
                except Exception:
                    continue

            # Fallback: try clicking any prominent button with "Add" text
            try:
                await self._page.click(
                    'button:has-text("Add to cart")', timeout=5000
                )
                await asyncio.sleep(2)
                logger.info(f"Added to cart (fallback): {product.name}")
                return True
            except Exception:
                pass

            logger.warning(f"Could not find Add to Cart button for: {product.name}")
            return False

        except Exception as e:
            logger.error(f"Error adding {product.name} to cart: {e}")
            return False

    async def add_to_cart_from_search(self, product_index: int = 0) -> bool:
        """Add a product to cart directly from search results page.

        This clicks the Add button on a search result without navigating
        to the product page first, which is faster.

        Args:
            product_index: 0-based index of the product in search results

        Returns:
            True if successfully added
        """
        if not self._page:
            return False

        try:
            # Find all Add to Cart buttons on the search page
            add_buttons = await self._page.query_selector_all(
                'button:has-text("Add to cart"), '
                + '[data-automation-id="add-to-cart-btn"]'
            )

            if product_index < len(add_buttons):
                await add_buttons[product_index].click()
                await asyncio.sleep(2)

                # Handle any popups (like "Added to cart" confirmation)
                try:
                    close_btn = await self._page.wait_for_selector(
                        'button:has-text("Close"), '
                        + 'button[aria-label="Close"], '
                        + '.close-flyout',
                        timeout=3000,
                    )
                    if close_btn:
                        await close_btn.click()
                except Exception:
                    pass

                return True

            return False
        except Exception as e:
            logger.error(f"Error adding item from search: {e}")
            return False

    async def get_cart_total(self) -> Optional[float]:
        """Navigate to cart and get the current total."""
        if not self._page:
            return None

        try:
            await self._page.goto(WALMART_CART_URL, timeout=PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(2)

            total_text = await self._page.evaluate("""() => {
                const selectors = [
                    '[data-testid="subtotal"] .f2',
                    '.Cart-SubTotal .Price',
                    '[data-automation-id="cart-subtotal"]',
                    'span:has-text("Subtotal")',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) return el.textContent;
                }
                // Fallback: search for subtotal pattern
                const body = document.body.innerText;
                const match = body.match(/Subtotal\\s*\\(?\\d+ items?\\)?\\s*\\$([\\d,]+\\.\\d{2})/i);
                return match ? '$' + match[1] : null;
            }""")

            if total_text:
                match = re.search(r"\$([\d,]+\.?\d*)", total_text)
                if match:
                    return float(match.group(1).replace(",", ""))

            return None
        except Exception as e:
            logger.error(f"Error getting cart total: {e}")
            return None

    async def search_and_compare(
        self, item_name: str, alternatives: list[str] | None = None
    ) -> dict:
        """Search for an item and its alternatives, comparing prices.

        Args:
            item_name: The primary item to search for
            alternatives: Optional list of alternative items to compare

        Returns:
            Dict with primary results and alternative results with comparison
        """
        primary = await self.search_products(item_name, max_results=5)

        result = {
            "primary_item": item_name,
            "primary_results": primary,
            "alternatives": {},
            "best_deal": None,
            "sale_alternatives": [],
        }

        if alternatives:
            for alt in alternatives:
                alt_results = await self.search_products(alt, max_results=5)
                result["alternatives"][alt] = alt_results

                # Check if any alternatives are on sale
                for p in alt_results:
                    if p.on_sale:
                        result["sale_alternatives"].append({
                            "item": alt,
                            "product": p,
                            "suggestion": (
                                f"Consider {alt} instead of {item_name} - "
                                f"{p.name} is on sale at {p.display()}"
                            ),
                        })

        # Find best deal across all results
        all_products = list(primary)
        for alt_results in result["alternatives"].values():
            all_products.extend(alt_results)

        if all_products:
            on_sale = [p for p in all_products if p.on_sale]
            if on_sale:
                result["best_deal"] = min(on_sale, key=lambda p: p.price)
            else:
                result["best_deal"] = min(all_products, key=lambda p: p.price)

        return result

    async def screenshot(self, path: str = "/tmp/walmart_screenshot.png") -> str:
        """Take a screenshot for debugging."""
        if self._page:
            await self._page.screenshot(path=path)
            return path
        return ""

    async def close(self) -> None:
        """Close the browser and playwright process."""
        try:
            if self._browser:
                await self._browser.close()
        except Exception as e:
            logger.warning(f"Error closing browser: {e}")
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"Error stopping playwright: {e}")
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        logger.info("Browser closed")

    @property
    def is_ready(self) -> bool:
        return self._page is not None

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    @property
    def is_headed(self) -> bool:
        return not self._headless

    @property
    def is_cdp(self) -> bool:
        return self._cdp_url is not None
