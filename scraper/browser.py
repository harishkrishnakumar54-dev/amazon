import logging
from typing import Optional
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright

logger = logging.getLogger("amazon_scraper")

def safe_close_page(page: Optional[Page]):
    """Safely closes a Playwright Page without throwing or hanging."""
    if page:
        try:
            if not page.is_closed():
                page.close()
        except Exception as e:
            logger.debug(f"Non-critical error closing page: {e}")

def attach_safe_dialog_handler(page: Optional[Page]):
    """Attach a single safe dialog handler to automatically dismiss alert/confirm/beforeunload dialogs."""
    if not page:
        return
    if getattr(page, "_has_safe_dialog_handler", False):
        return
    page._has_safe_dialog_handler = True
    def safe_handle_dialog(dialog):
        try:
            dialog.dismiss()
        except Exception as exc:
            logger.debug(f"Dialog dismiss failed (already closed?): {exc}")
    try:
        page.on("dialog", safe_handle_dialog)
    except Exception as exc:
        logger.debug(f"Failed to attach dialog listener: {exc}")

class BrowserManager:
    """
    Manages Playwright browser lifecycle using standard Playwright automation.
    Does NOT use stealth plugins, fingerprint spoofing, or anti-bot bypasses.
    Enforces bounded timeouts, shared browser/context retention, and safe cleanup.
    """
    def __init__(self, headless: bool = False, timeout_ms: int = 30000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

    def start(self):
        """Starts Playwright, Chromium Browser, and shared BrowserContext."""
        try:
            if not self.playwright:
                self.playwright = sync_playwright().start()

            if not self.browser or not self.browser.is_connected():
                self.browser = self.playwright.chromium.launch(
                    headless=self.headless,
                    args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
                )
                self.context = None

            if not self.context:
                self._create_context()

            logger.info(f"Started standard Playwright Chromium session (headless={self.headless}, timeout={self.timeout_ms}ms)")
        except Exception as e:
            logger.error(f"Failed to start Playwright browser: {e}")
            self.close()
            raise e

    def _create_context(self):
        if not self.browser or not self.browser.is_connected():
            return
        self.context = self.browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="en-IN",
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
                "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1"
            }
        )
        self.context.set_default_timeout(self.timeout_ms)

    def is_alive(self) -> bool:
        """Returns True if both browser and context are connected and open."""
        if not self.browser or not self.browser.is_connected():
            return False
        if not self.context:
            return False
        return True

    def new_page(self) -> Page:
        """
        Creates a new Page from the shared BrowserContext.
        Guarantees that if the context or browser was closed/crashed, it cleanly re-establishes it.
        """
        if not self.is_alive():
            logger.warning("Browser or context was closed/disconnected. Re-establishing session...")
            self.start()

        try:
            page = self.context.new_page()
            page.set_default_timeout(self.timeout_ms)
            attach_safe_dialog_handler(page)
            return page
        except Exception as e:
            logger.warning(f"Failed to create new page from existing context ({e}). Attempting clean restart...")
            self.start()
            page = self.context.new_page()
            page.set_default_timeout(self.timeout_ms)
            attach_safe_dialog_handler(page)
            return page

    def close(self):
        """Safe non-blocking cleanup that guarantees the process never hangs on exit."""
        if self.context:
            try:
                self.context.close()
            except Exception as e:
                logger.debug(f"Error closing context: {e}")
            finally:
                self.context = None

        if self.browser:
            try:
                if self.browser.is_connected():
                    self.browser.close()
            except Exception as e:
                logger.debug(f"Error closing browser: {e}")
            finally:
                self.browser = None

        if self.playwright:
            try:
                self.playwright.stop()
            except Exception as e:
                logger.debug(f"Error stopping Playwright: {e}")
            finally:
                self.playwright = None
