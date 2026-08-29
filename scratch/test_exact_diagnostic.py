import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.browser import BrowserManager
from scraper.amazon_search import (
    AmazonSearchScraper,
    is_valid_amazon_html,
    is_legitimate_zero_results,
    extract_products_from_page
)

def run_exact_diagnostic():
    target_url = "https://www.amazon.in/s?k=Men%27s+Casual+Shoes"
    print("==================================================")
    print("EXACT AMAZON PLAYWRIGHT SCRAPER DIAGNOSTIC TEST")
    print(f"Target URL: {target_url}")
    print("==================================================")

    bm = BrowserManager(headless=True)
    bm.start()
    print("1. Browser launched: YES")

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    print(f"2. User agent: {user_agent}")

    page = bm.new_page()

    nav_exception = None
    exc_type = "None"
    exc_msg = "None"
    response = None
    status_code = "None"
    resp_headers = {}
    content_type = "Unknown"

    try:
        response = page.goto(target_url, wait_until="commit", timeout=25000)
        if response:
            status_code = getattr(response, "status", "None")
            resp_headers = getattr(response, "headers", {})
            content_type = resp_headers.get("content-type", "Unknown")
    except Exception as e:
        nav_exception = e
        exc_type = type(e).__name__
        exc_msg = str(e)

    # Settle page
    try:
        page.wait_for_timeout(1000)
    except Exception:
        pass

    cur_url = getattr(page, "url", target_url) or target_url
    page_title = ""
    html_content = ""
    try:
        page_title = page.title() or ""
        html_content = page.content() or ""
    except Exception:
        pass

    html_len = len(html_content)
    is_valid, valid_reason = is_valid_amazon_html(page, html_content, cur_url)
    
    selector_count = 0
    if is_valid:
        try:
            selector_count = len(page.query_selector_all("a[href*='/dp/']"))
        except Exception:
            selector_count = 0

    print(f"3. Navigation exception: {exc_msg if nav_exception else 'None'}")
    print(f"4. Exception type: {exc_type}")
    print(f"5. Exception message: {exc_msg}")
    print(f"6. Current URL: {cur_url}")
    print(f"7. Page title: {page_title}")
    print(f"8. HTML length: {html_len}")
    print(f"9. Content type if available: {content_type}")
    print(f"10. Amazon markers: {'YES' if is_valid else 'NO'}")
    print(f"11. Product selector count: {selector_count}")
    print(f"12. Response status if available: {status_code}")
    print(f"13. Response headers if available: {resp_headers.get('content-type', 'None')}")

    print("\n----------------------------------------")
    print("PRODUCTION SCRAPER STATE VERIFICATION")
    print("----------------------------------------")
    scraper = AmazonSearchScraper(page, max_retries=3, browser_mgr=bm)
    nav_result = scraper.navigate_and_discover(target_url, limit=5, category_name="Men's Casual Shoes")
    
    print(f"Navigation success: {nav_result.success}")
    print(f"Navigation status: {nav_result.status}")
    print(f"Navigation reason: {nav_result.reason}")
    print(f"Products extracted count: {len(nav_result.products)}")
    if nav_result.products:
        for idx, p in enumerate(nav_result.products[:3], 1):
            print(f"  {idx}. ASIN: {p['asin']} | Title: {p['product_title'][:50]}")

    bm.close()

if __name__ == "__main__":
    run_exact_diagnostic()
