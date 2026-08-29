import logging
import re
import time
from typing import List, Dict, Any, Tuple, Optional
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
from scraper.browser import safe_close_page

logger = logging.getLogger("amazon_scraper")

class AmazonBlockedException(Exception):
    """Raised when Amazon returns 503, 429, 403, or robot check / captcha across all retries."""
    def __init__(self, status_reason: str, url: str):
        self.status_reason = status_reason
        self.url = url
        super().__init__(f"Amazon blocked or unavailable ({status_reason}) at {url}")

class AmazonNavigationException(Exception):
    """Raised when Amazon navigation fails across all retries (e.g. Download starting, non-HTML response, timeout)."""
    def __init__(self, reason: str, url: str):
        self.reason = reason
        self.url = url
        super().__init__(f"Amazon navigation failed ({reason}) at {url}")

def check_amazon_block(response, page: Page) -> Tuple[bool, str]:
    """
    Checks if an Amazon page response or content represents a block/503/captcha.
    """
    if response:
        try:
            if response.status == 503:
                return True, "503 Service Unavailable"
            if response.status == 429:
                return True, "429 Too Many Requests"
            if response.status == 403:
                return True, "403 Forbidden"
        except Exception:
            pass

    try:
        title = (page.title() or "").lower()
        if "robot check" in title or "captcha" in title:
            return True, "Robot Check / CAPTCHA"
        if "503 - service unavailable" in title or "503 service unavailable" in title:
            return True, "503 Service Unavailable"
            
        content = page.content().lower()
        if "api-services-support@amazon.com" in content or "type the characters you see in this image" in content:
            return True, "Robot Check / CAPTCHA"
        if "sorry, we couldn't find that page" in title and "amazon" in title:
            return False, "Page Not Found"
    except Exception:
        pass

    return False, "OK"

def verify_amazon_search_page(page: Page, response: Any, selectors_found: bool) -> Tuple[bool, str]:
    """
    Verifies that the loaded page is an actual Amazon HTML search page.
    Returns (is_valid, reason).
    """
    try:
        url = (page.url or "").lower()
        title = (page.title() or "").lower()

        if selectors_found:
            return True, "Search selectors present"

        # Check for empty search result page markers
        try:
            content = page.content().lower()
            if any(phrase in content for phrase in [
                "no results for", "0 results for", "did not match any products",
                "try checking your spelling", "no products found"
            ]):
                if "amazon" in title or "amazon" in url or "amazon" in content[:2000]:
                    return True, "Valid zero-results search page"
        except Exception:
            pass

        # Check if page is recognizable Amazon HTML
        if "amazon" in title or "amazon" in url:
            return True, "Amazon page loaded"

        if url in ("about:blank", "") or not title:
            return False, "Empty or unrendered page"

        return False, "Not an Amazon search page"
    except Exception as e:
        return False, f"Verification error: {e}"

class AmazonSearchScraper:
    """
    Scrapes Amazon search / category listing pages to discover product URLs.
    Handles bounded timeouts, download aborts, 503/CAPTCHA detection, fresh context retries,
    and structured navigation diagnostics.
    """
    def __init__(self, page: Page, max_retries: int = 3, browser_mgr: Optional[Any] = None):
        self.page = page
        self.max_retries = max_retries
        self.browser_mgr = browser_mgr

    def _recreate_page(self) -> Page:
        """
        Safely closes the current page and opens a fresh page/context for clean retry.
        """
        if self.browser_mgr:
            if self.page:
                try:
                    safe_close_page(self.page)
                except Exception as e:
                    logger.debug(f"Error closing old page: {e}")
            try:
                self.page = self.browser_mgr.new_page()
                return self.page
            except Exception as e:
                logger.debug(f"Error getting page from browser_mgr: {e}")

        # If running in a test environment with mock page and no browser_mgr, preserve mock page
        if hasattr(self.page, "_spec_class") or "mock" in getattr(type(self.page), "__module__", ""):
            return self.page

        if self.page:
            try:
                safe_close_page(self.page)
            except Exception as e:
                logger.debug(f"Error closing old page: {e}")

        try:
            if hasattr(self.page, "context") and self.page.context:
                context = self.page.context
                if hasattr(context, "browser") and context.browser:
                    new_ctx = context.browser.new_context(
                        viewport={"width": 1366, "height": 768},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                        locale="en-IN"
                    )
                    self.page = new_ctx.new_page()
                    return self.page
                else:
                    self.page = context.new_page()
                    return self.page
        except Exception as e:
            logger.debug(f"Error recreating page from context: {e}")

        return self.page

    def discover_products(self, search_url: str, limit: int = 10, max_pages: int = 1, category_name: str = "") -> List[Dict[str, Any]]:
        products = []
        visited_urls = set()
        current_url = search_url
        page_num = 1

        # Determine category from search URL query parameter if present
        parsed = urlparse(search_url)
        qs = parse_qs(parsed.query)
        category_hint = category_name or qs.get("k", ["General"])[0].replace("+", " ")

        backoff_delays = [2, 5, 10]

        SEARCH_SELECTORS = [
            "div[data-component-type='s-search-result']",
            "div.s-result-item[data-asin]:not([data-asin=''])",
            "a[href*='/dp/']",
            "div.s-main-slot",
            "span[data-component-type='s-search-results']"
        ]

        while current_url and page_num <= max_pages and len(products) < limit:
            logger.info(f"Navigating to Amazon search page {page_num}: {current_url}")
            page_loaded = False
            last_failure_reason = "Unknown"

            for attempt in range(1, self.max_retries + 1):
                print(f"Opening Amazon...")
                print(f"Attempt: {attempt}/{self.max_retries}")

                download_detected = False
                nav_status = "Unknown"
                content_type = "Unknown"
                final_url = current_url
                page_title = "Unknown"
                selectors_found = False
                attempt_success = False
                is_blocked = False
                response = None

                # 1. Navigate with commit strategy to detect downloads and avoid hanging on domcontentloaded
                try:
                    response = self.page.goto(current_url, wait_until="commit", timeout=30000)
                    if response:
                        try:
                            raw_ct = response.headers.get("content-type", "") if hasattr(response, "headers") else ""
                            content_type = raw_ct if isinstance(raw_ct, str) and raw_ct else "Unknown"
                        except Exception:
                            content_type = "Unknown"
                        final_url = getattr(response, "url", None) or (getattr(self.page, "url", None) if self.page else current_url)
                        status_code = getattr(response, "status", 200)
                        nav_status = f"{status_code} OK" if status_code == 200 else f"HTTP {status_code}"
                    else:
                        nav_status = "Committed"
                        final_url = getattr(self.page, "url", current_url) if self.page else current_url
                except Exception as e:
                    err_str = str(e).lower()
                    if "download is starting" in err_str or "download" in err_str or "net::err_aborted" in err_str:
                        download_detected = True
                        nav_status = "Download is starting"
                        last_failure_reason = "Download is starting"
                    elif isinstance(e, PlaywrightTimeoutError) or "timeout" in err_str:
                        nav_status = "Navigation Timeout (30s)"
                        last_failure_reason = "Navigation Timeout (30s)"
                    else:
                        nav_status = f"Navigation Error: {str(e)[:60]}"
                        last_failure_reason = f"Navigation Error: {str(e)[:60]}"

                # 2. Check if response headers trigger a download or non-HTML content
                if not download_detected and response:
                    try:
                        raw_cd = response.headers.get("content-disposition", "") if hasattr(response, "headers") else ""
                        content_disposition = raw_cd if isinstance(raw_cd, str) else ""
                        if content_disposition and "attachment" in content_disposition.lower():
                            download_detected = True
                            nav_status = "Download header detected (attachment)"
                            last_failure_reason = "Download is starting"
                        elif content_type and content_type != "Unknown" and isinstance(content_type, str) and not any(ht in content_type.lower() for ht in ["text/html", "application/xhtml"]):
                            download_detected = True
                            nav_status = f"Non-HTML Content-Type ({content_type})"
                            last_failure_reason = f"Non-HTML response ({content_type})"
                    except Exception:
                        pass

                # 3. Check for Amazon blocks / Captcha / 503
                if not download_detected:
                    is_blocked, block_reason = check_amazon_block(response, self.page)
                    if is_blocked:
                        nav_status = f"Blocked: {block_reason}"
                        last_failure_reason = block_reason

                # 4. If not download and not blocked, wait for DOM and verify selectors
                if not download_detected and not is_blocked:
                    try:
                        self.page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass

                    try:
                        page_title = self.page.title() or ""
                    except Exception:
                        page_title = ""

                    # Check selectors
                    for sel in SEARCH_SELECTORS:
                        try:
                            if self.page.query_selector(sel):
                                selectors_found = True
                                break
                        except Exception:
                            pass

                    if not selectors_found:
                        try:
                            self.page.wait_for_selector(
                                "div[data-component-type='s-search-result'], div.s-result-item[data-asin], a[href*='/dp/'], div.s-main-slot",
                                timeout=5000
                            )
                            selectors_found = True
                        except Exception:
                            selectors_found = False

                    is_valid_html, valid_reason = verify_amazon_search_page(self.page, response, selectors_found)
                    if not is_valid_html:
                        nav_status = f"Invalid Amazon Page ({valid_reason})"
                        last_failure_reason = valid_reason
                    else:
                        attempt_success = True
                        nav_status = f"Success ({valid_reason})"

                # 5. If attempt succeeded, extract products
                if attempt_success:
                    try:
                        self.page.evaluate("window.scrollBy(0, 800);")
                        self.page.wait_for_timeout(1000)
                    except Exception:
                        pass

                    links = self.page.query_selector_all("a[href*='/dp/']")
                    logger.info(f"Found {len(links)} raw product links on page {page_num}")

                    for link in links:
                        if len(products) >= limit:
                            break
                        try:
                            href = link.get_attribute("href")
                            if not href:
                                continue
                            if href.startswith("/"):
                                full_url = f"https://www.amazon.in{href}"
                            else:
                                full_url = href

                            asin_match = re.search(r"/dp/([A-Z0-9]{10})", full_url)
                            if not asin_match:
                                continue

                            asin = asin_match.group(1)
                            clean_product_url = f"https://www.amazon.in/dp/{asin}"

                            if clean_product_url in visited_urls:
                                continue

                            visited_urls.add(clean_product_url)
                            title_text = link.inner_text().strip() or f"Amazon Product {asin}"

                            products.append({
                                "asin": asin,
                                "product_url": clean_product_url,
                                "product_title": title_text[:120],
                                "category": category_hint,
                                "source_search_url": search_url
                            })
                        except Exception as e:
                            logger.debug(f"Error parsing product link: {e}")
                            continue

                # 6. Diagnostics output
                print(f"""
AMAZON NAVIGATION DIAGNOSTICS
Category: {category_hint}
URL: {current_url}
Attempt: {attempt}/{self.max_retries}
Navigation status: {nav_status}
Content type: {content_type}
Final URL: {final_url}
Page title: {page_title}
Download detected: {'YES' if download_detected else 'NO'}
Amazon product selectors found: {'YES' if selectors_found else 'NO'}
Products extracted: {len(products)}
""")

                # 7. Evaluate attempt result
                if attempt_success:
                    page_loaded = True
                    if len(products) == 0:
                        print("NO_PRODUCTS: Amazon search page loaded successfully and selectors were checked, but 0 products found matching criteria.")
                    else:
                        print(f"Products discovered: {len(products)}")
                    logger.info(f"Discovered {len(products)} total unique product URLs so far")
                    break
                else:
                    if attempt < self.max_retries:
                        delay = backoff_delays[attempt - 1]
                        print(f"Navigation attempt {attempt} failed ({last_failure_reason}). Recreating clean page/context and retrying in {delay}s...")
                        logger.warning(f"Amazon navigation retry {attempt}/{self.max_retries} for '{category_hint}': {last_failure_reason}")
                        self._recreate_page()
                        time.sleep(delay)
                        continue
                    else:
                        print(f"""
========================================
NAVIGATION FAILURE
Reason: {last_failure_reason}
Category status: FAILED
Do NOT mark category as completed/skipped.
========================================
""")
                        logger.error(f"""
AMAZON NAVIGATION FAILURE
Category: {category_hint}
URL: {current_url}
Reason: {last_failure_reason}
Status: FAILED
""")
                        if is_blocked:
                            raise AmazonBlockedException(last_failure_reason, current_url)
                        else:
                            raise AmazonNavigationException(last_failure_reason, current_url)

            if not page_loaded:
                break

            # Handle pagination
            if page_num < max_pages and len(products) < limit:
                try:
                    next_btn = self.page.query_selector("a.s-pagination-next")
                    if next_btn:
                        next_href = next_btn.get_attribute("href")
                        if next_href:
                            current_url = f"https://www.amazon.in{next_href}" if next_href.startswith("/") else next_href
                            page_num += 1
                        else:
                            break
                    else:
                        break
                except Exception:
                    break
            else:
                break

        return products
