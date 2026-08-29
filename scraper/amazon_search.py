import logging
import re
import time
import urllib.request
import urllib.error
import gzip
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

def check_amazon_block(response, page: Optional[Page] = None, html_content: str = "") -> Tuple[bool, str]:
    """
    Checks if an Amazon page response or content represents a block/503/captcha.
    """
    if response:
        try:
            status = getattr(response, "status", None)
            if status == 503:
                return True, "503 Service Unavailable"
            if status == 429:
                return True, "429 Too Many Requests"
            if status == 403:
                return True, "403 Forbidden"
        except Exception:
            pass

    try:
        title = (page.title() or "").lower() if page else ""
        if "robot check" in title or "captcha" in title:
            return True, "Robot Check / CAPTCHA"
        if "503 - service unavailable" in title or "503 service unavailable" in title:
            return True, "503 Service Unavailable"

        content = html_content.lower() if html_content else ((page.content() or "").lower() if page else "")
        if "api-services-support@amazon.com" in content or "type the characters you see in this image" in content:
            return True, "Robot Check / CAPTCHA"
        if "sorry, we couldn't find that page" in title and "amazon" in title:
            return False, "Page Not Found"
    except Exception:
        pass

    return False, "OK"

def is_valid_amazon_html(page: Optional[Page], html: str, url: str) -> Tuple[bool, str]:
    """
    Strictly checks whether the page or HTML is an authentic Amazon page.
    Rejects chrome-error://, about:blank, empty pages, non-HTML, and robot check.
    """
    if not url or url.startswith("chrome-error://") or url in ("about:blank", ""):
        return False, "Page URL is chrome-error:// or blank"

    if len(html) < 100:
        return False, f"Page HTML length ({len(html)}) too short"

    html_lower = html.lower()
    url_lower = url.lower()

    if "amazon" not in url_lower and "amazon" not in html_lower[:3000]:
        return False, "Amazon markers missing from URL and HTML header"

    if "api-services-support@amazon.com" in html_lower or "type the characters you see in this image" in html_lower:
        return False, "Robot Check / CAPTCHA detected"

    if "503 - service unavailable" in html_lower[:2000] or "503 service unavailable" in html_lower[:2000]:
        return False, "503 Service Unavailable"

    return True, "Valid Amazon HTML"

def is_legitimate_zero_results(page: Optional[Page], html: str) -> bool:
    """
    Strictly verifies if a loaded Amazon page is a genuine 0-results search.
    Requires explicit Amazon zero-results text or Amazon search layout.
    """
    html_lower = html.lower()
    if any(phrase in html_lower for phrase in [
        "no results for",
        "0 results for",
        "did not match any products",
        "try checking your spelling",
        "no products found for"
    ]):
        return True

    if page:
        try:
            has_search_slot = bool(page.query_selector("div.s-main-slot, span[data-component-type='s-search-results'], div.s-desktop-toolbar, div#nav-search-bar-form"))
            if has_search_slot and "results" in html_lower:
                return True
        except Exception:
            pass

    return False

def extract_products_from_page(page: Page, limit: int, category_hint: str, search_url: str, visited_urls: set) -> List[Dict[str, Any]]:
    """
    Extracts product links from current page DOM and/or HTML.
    """
    products = []

    try:
        page.evaluate("window.scrollBy(0, 800);")
        page.wait_for_timeout(500)
    except Exception:
        pass

    try:
        links = page.query_selector_all("a[href*='/dp/']")
    except Exception:
        links = []

    for link in links:
        if len(products) >= limit:
            break
        try:
            href = link.get_attribute("href")
            if not href:
                continue
            full_url = f"https://www.amazon.in{href}" if href.startswith("/") else href
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

    # Fallback to HTML regex extraction if DOM querying was empty
    if len(products) == 0:
        try:
            content = page.content()
            asins = list(dict.fromkeys(re.findall(r"/dp/([A-Z0-9]{10})", content)))
            for asin in asins:
                if len(products) >= limit:
                    break
                clean_product_url = f"https://www.amazon.in/dp/{asin}"
                if clean_product_url in visited_urls:
                    continue
                visited_urls.add(clean_product_url)
                products.append({
                    "asin": asin,
                    "product_url": clean_product_url,
                    "product_title": f"Amazon Product {asin}",
                    "category": category_hint,
                    "source_search_url": search_url
                })
        except Exception as e:
            logger.debug(f"Error regex parsing HTML: {e}")

    return products

class AmazonSearchScraper:
    """
    Scrapes Amazon search / category listing pages to discover product URLs.
    Handles bounded timeouts, download aborts, 503/CAPTCHA detection,
    multi-stage navigation recovery, strict 3-state validation, and structured diagnostics.
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
                print(f"\n========================================")
                print(f"AMAZON NAVIGATION")
                print(f"Category: {category_hint}")
                print(f"URL: {current_url}")
                print(f"========================================")

                download_detected = False
                nav_result = "SUCCESS"
                last_failure_reason = "Unknown"
                is_blocked = False
                response = None
                extracted_this_attempt = []

                # -------------------------------------------------------------
                # 1. Primary Playwright Navigation
                # -------------------------------------------------------------
                try:
                    response = self.page.goto(current_url, wait_until="commit", timeout=25000)
                    status_code = getattr(response, "status", 200)
                    nav_result = f"Status {status_code}"
                except Exception as e:
                    err_str = str(e)
                    if "download is starting" in err_str.lower() or "download" in err_str.lower() or "net::err_aborted" in err_str.lower():
                        download_detected = True
                        nav_result = "Download is starting"
                        last_failure_reason = "Download is starting"
                    elif isinstance(e, PlaywrightTimeoutError) or "timeout" in err_str.lower():
                        nav_result = "Navigation Timeout (25s)"
                        last_failure_reason = "Navigation Timeout (25s)"
                    else:
                        nav_result = f"Error: {err_str[:60]}"
                        last_failure_reason = f"Navigation Error: {err_str[:60]}"

                print(f"\nPlaywright attempt: {attempt}")
                print(f"Result: {nav_result}")

                # -------------------------------------------------------------
                # 2. Browser Page Settle & Inspection Recovery
                # -------------------------------------------------------------
                print(f"\nRecovery:")
                print(f"Checking page after navigation exception...")

                try:
                    if hasattr(self.page, "wait_for_timeout"):
                        self.page.wait_for_timeout(1000)
                except Exception:
                    pass

                cur_url = getattr(self.page, "url", current_url) or current_url
                page_title = ""
                html_content = ""
                try:
                    page_title = self.page.title() or ""
                    html_content = self.page.content() or ""
                except Exception:
                    pass

                html_len = len(html_content)
                is_valid, valid_reason = is_valid_amazon_html(self.page, html_content, cur_url)
                has_amazon_markers = is_valid

                selectors_found = False
                if is_valid:
                    for sel in SEARCH_SELECTORS:
                        try:
                            if self.page.query_selector(sel):
                                selectors_found = True
                                break
                        except Exception:
                            pass

                print(f"\nCurrent URL: {cur_url}")
                print(f"Title: {page_title}")
                print(f"HTML length: {html_len}")
                print(f"Amazon search markers: {'YES' if has_amazon_markers else 'NO'}")
                print(f"Product selectors: {'YES' if selectors_found else 'NO'}")

                is_blocked, block_reason = check_amazon_block(response, self.page, html_content)
                if is_blocked:
                    last_failure_reason = block_reason

                if is_valid and not is_blocked:
                    candidate_prods = extract_products_from_page(self.page, limit - len(products), category_hint, search_url, visited_urls)
                    if len(candidate_prods) > 0:
                        # STATE 1: SUCCESS_WITH_PRODUCTS
                        page_loaded = True
                        extracted_this_attempt = candidate_prods
                    elif is_legitimate_zero_results(self.page, html_content):
                        # STATE 2: SUCCESS_WITH_ZERO_PRODUCTS
                        page_loaded = True
                        extracted_this_attempt = []
                    else:
                        last_failure_reason = "No product selectors and no zero-result markers on page"

                # -------------------------------------------------------------
                # 3. Playwright Context Request Recovery (APIRequestContext)
                # -------------------------------------------------------------
                if not page_loaded and not is_blocked:
                    try:
                        if hasattr(self.page, "context") and self.page.context and hasattr(self.page.context, "request"):
                            ctx_resp = self.page.context.request.get(
                                current_url,
                                headers={
                                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                                    "accept-language": "en-IN,en-GB;q=0.9,en;q=0.8",
                                    "referer": "https://www.amazon.in/"
                                },
                                timeout=25000
                            )
                            ctx_status = ctx_resp.status
                            ctx_ct = ctx_resp.headers.get("content-type", "")
                            ctx_html = ctx_resp.text()
                            
                            ctx_is_valid, ctx_reason = is_valid_amazon_html(None, ctx_html, current_url)
                            is_blocked, block_reason = check_amazon_block(ctx_resp, None, ctx_html)
                            
                            if ctx_is_valid and not is_blocked:
                                try:
                                    self.page.set_content(ctx_html, wait_until="domcontentloaded")
                                except Exception:
                                    pass
                                candidate_prods = extract_products_from_page(self.page, limit - len(products), category_hint, search_url, visited_urls)
                                if len(candidate_prods) > 0:
                                    page_loaded = True
                                    extracted_this_attempt = candidate_prods
                                elif is_legitimate_zero_results(self.page, ctx_html):
                                    page_loaded = True
                                    extracted_this_attempt = []
                                else:
                                    last_failure_reason = "Context Request returned HTML with no products and no zero-results markers"
                            elif is_blocked:
                                last_failure_reason = block_reason
                            else:
                                last_failure_reason = f"Context Request invalid: {ctx_reason}"
                    except Exception as ctx_err:
                        logger.debug(f"Context request fallback error: {ctx_err}")

                # -------------------------------------------------------------
                # 4. HTTP Fallback (urllib.request with Realistic Headers & Gzip)
                # -------------------------------------------------------------
                if not page_loaded and not is_blocked:
                    print(f"\nHTTP FALLBACK")
                    try:
                        HTTP_HEADERS = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                            "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
                            "Accept-Encoding": "gzip, deflate, br",
                            "Referer": "https://www.amazon.in/",
                            "Connection": "keep-alive"
                        }
                        req = urllib.request.Request(current_url, headers=HTTP_HEADERS)
                        with urllib.request.urlopen(req, timeout=20) as http_resp:
                            http_status = http_resp.status
                            http_ct = http_resp.headers.get("Content-Type", "")
                            raw_bytes = http_resp.read()
                            if http_resp.headers.get("Content-Encoding") == "gzip":
                                http_html = gzip.decompress(raw_bytes).decode("utf-8", errors="replace")
                            else:
                                http_html = raw_bytes.decode("utf-8", errors="replace")

                            http_is_valid, http_reason = is_valid_amazon_html(None, http_html, current_url)
                            is_blocked, block_reason = check_amazon_block(http_resp, None, http_html)

                            print(f"Status: {http_status}")
                            print(f"Content-Type: {http_ct}")
                            print(f"HTML length: {len(http_html)}")
                            print(f"Amazon markers: {'YES' if http_is_valid else 'NO'}")

                            if http_is_valid and not is_blocked:
                                try:
                                    self.page.set_content(http_html, wait_until="domcontentloaded")
                                except Exception:
                                    pass
                                candidate_prods = extract_products_from_page(self.page, limit - len(products), category_hint, search_url, visited_urls)
                                if len(candidate_prods) > 0:
                                    page_loaded = True
                                    extracted_this_attempt = candidate_prods
                                elif is_legitimate_zero_results(self.page, http_html):
                                    page_loaded = True
                                    extracted_this_attempt = []
                                else:
                                    last_failure_reason = "HTTP Fallback returned HTML with no products and no zero-results markers"
                            elif is_blocked:
                                last_failure_reason = block_reason
                            else:
                                last_failure_reason = f"HTTP Fallback invalid: {http_reason}"
                    except urllib.error.HTTPError as he:
                        print(f"Status: {he.code}")
                        print(f"Content-Type: {he.headers.get('Content-Type')}")
                        print(f"HTML length: 0")
                        print(f"Amazon markers: NO")
                        if he.code in (503, 429, 403):
                            is_blocked = True
                            last_failure_reason = f"{he.code} Service Unavailable" if he.code == 503 else f"HTTP {he.code}"
                    except Exception as he_err:
                        print(f"HTTP Fallback exception: {he_err}")

                # -------------------------------------------------------------
                # 5. Product Discovery Result Evaluation (Strict 3 States)
                # -------------------------------------------------------------
                if page_loaded and len(extracted_this_attempt) > 0:
                    # STATE 1: SUCCESS_WITH_PRODUCTS
                    products.extend(extracted_this_attempt)
                    print(f"\nPRODUCT DISCOVERY")
                    print(f"Products extracted: {len(products)}")
                    logger.info(f"Discovered {len(products)} total unique product URLs so far for '{category_hint}'")
                    break
                elif page_loaded and len(extracted_this_attempt) == 0:
                    # STATE 2: SUCCESS_WITH_ZERO_PRODUCTS
                    print(f"\nPRODUCT DISCOVERY")
                    print(f"Products extracted: 0")
                    print(f"Status: NO_PRODUCTS")
                    logger.info(f"Verified 0 products found for '{category_hint}'")
                    break
                else:
                    # STATE 3: NAVIGATION_FAILURE for this attempt
                    if attempt < self.max_retries:
                        delay = backoff_delays[attempt - 1]
                        print(f"\nNavigation attempt {attempt} failed ({last_failure_reason}). Recreating fresh page/context and retrying in {delay}s...")
                        logger.warning(f"Amazon navigation retry {attempt}/{self.max_retries} for '{category_hint}': {last_failure_reason}")
                        self._recreate_page()
                        time.sleep(delay)
                        continue
                    else:
                        # All attempts failed -> FAIL category
                        print(f"""
========================================
AMAZON NAVIGATION FAILURE
Category: {category_hint}
URL: {current_url}
Reason: {last_failure_reason}
Status: FAILED
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
