"""
Browser Automator - CDP-based browser automation for MediaCrawler
Uses Chrome DevTools Protocol to automatically click start buttons.
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BrowserAutomator:
    """
    Browser automation using Chrome DevTools Protocol.

    Connects to an existing Chrome browser (started with --remote-debugging-port=9222)
    and clicks the start button on MediaCrawler WebUI.
    """

    def __init__(self, ws_url: Optional[str] = None):
        self.ws_url = ws_url or "ws://127.0.0.1:9222/devtools/browser"
        self._browser = None
        self._page = None
        self._playwright = None

    async def connect(self):
        """Connect to local Chrome browser via CDP."""
        from playwright.async_api import async_playwright

        self._playwright = async_playwright()
        await self._playwright.start()

        # Connect to existing browser with CDP
        self._browser = await self._playwright.chromium.connect_over_cdp(self.ws_url)
        context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
        self._page = context.pages[0] if context.pages else await context.new_page()

        logger.info(f"Connected to Chrome via CDP: {self.ws_url}")

    async def click_start_button(self, page_url: str = "http://127.0.0.1:8000/crawler", timeout: int = 30000):
        """
        Navigate to MediaCrawler page and click the start button.

        Args:
            page_url: URL of the MediaCrawler WebUI
            timeout: Timeout for button click in milliseconds
        """
        if not self._page:
            await self.connect()

        try:
            # Navigate to crawler page
            await self._page.goto(page_url, wait_until="networkidle", timeout=timeout)
            logger.info(f"Navigated to {page_url}")

            # Wait for page to be fully loaded
            await self._page.wait_for_load_state("domcontentloaded")

            # Try multiple selectors for the start button
            selectors = [
                "button:has-text('开始')",
                "button:has-text('开始采集')",
                "button:has-text('Start')",
                ".start-btn",
                "[class*='start']",
                "button.primary",
                "button[type='button']"
            ]

            for selector in selectors:
                try:
                    # Check if element exists
                    element = self._page.locator(selector).first
                    if await element.count() > 0:
                        await element.click(timeout=5000)
                        logger.info(f"Clicked button with selector: {selector}")
                        return True
                except Exception:
                    continue

            logger.warning("Could not find start button with any known selector")
            return False

        except Exception as e:
            logger.error(f"Failed to click start button: {e}")
            return False

    async def click_iframe_button(self, iframe_selector: str, button_selector: str, timeout: int = 30000):
        """
        Click a button inside an iframe.

        Args:
            iframe_selector: CSS selector for the iframe
            button_selector: CSS selector for the button inside iframe
        """
        if not self._page:
            await self.connect()

        try:
            # Get iframe
            iframe = self._page.frame_locator(iframe_selector)
            button = iframe.locator(button_selector).first

            await button.click(timeout=timeout)
            logger.info(f"Clicked button inside iframe: {button_selector}")
            return True

        except Exception as e:
            logger.error(f"Failed to click iframe button: {e}")
            return False

    async def get_page_content(self) -> str:
        """Get the current page HTML content."""
        if not self._page:
            return ""

        try:
            return await self._page.content()
        except Exception as e:
            logger.error(f"Failed to get page content: {e}")
            return ""

    async def take_screenshot(self, path: str):
        """Take a screenshot of the current page."""
        if not self._page:
            return False

        try:
            await self._page.screenshot(path=path)
            logger.info(f"Screenshot saved to {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            return False

    async def close(self):
        """Close browser connection."""
        if self._page:
            await self._page.close()
            self._page = None

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        logger.info("Browser connection closed")


async def main():
    """Test the browser automator."""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    automator = BrowserAutomator()

    try:
        await automator.connect()
        success = await automator.click_start_button()

        if success:
            print("Successfully clicked start button")
            sys.exit(0)
        else:
            print("Failed to click start button")
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        await automator.close()


if __name__ == '__main__':
    asyncio.run(main())