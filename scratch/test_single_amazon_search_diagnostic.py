import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.browser import BrowserManager
from scraper.amazon_search import (
    AmazonSearchScraper,
    is_valid_amazon_html,
    is_legitimate_zero_results,
    extract_products_from_page
)

def run_diagnostic():
    target_url = "https://www.amazon.in/s?k=Men%27s+Casual+Shoes"
    print("==================================================")
    print("AMAZON SINGLE CATEGORY DIAGNOSTIC TEST")
    print(f"Target URL: {target_url}")
    print("==================================================")

    print("Browser launched")
    bm = BrowserManager(headless=True)
    bm.start()

    print("Page created")
    page = bm.new_page()

    nav_exception = "None"
    nav_result = "SUCCESS"

    try:
        resp = page.goto(target_url, wait_until="commit", timeout=25000)
        status_code = getattr(resp, "status", 200)
        nav_result = f"Status {status_code}"
    except Exception as e:
        nav_result = "EXCEPTION"
        nav_exception = str(e)

    # Allow page to settle
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
    
    SEARCH_SELECTORS = [
        "div[data-component-type='s-search-result']",
        "div.s-result-item[data-asin]:not([data-asin=''])",
        "a[href*='/dp/']",
        "div.s-main-slot",
        "span[data-component-type='s-search-results']"
    ]
    
    selector_count = 0
    if is_valid:
        try:
            selector_count = len(page.query_selector_all("a[href*='/dp/']"))
        except Exception:
            selector_count = 0

    print(f"Navigation result: {nav_result}")
    print(f"Exception: {nav_exception}")
    print(f"Current URL: {cur_url}")
    print(f"Page title: {page_title}")
    print(f"HTML length: {html_len}")
    print(f"Amazon markers: {'YES' if is_valid else 'NO'}")
    print(f"Product selector count: {selector_count}")

    # Evaluate States
    candidate_products = []
    if is_valid:
        candidate_products = extract_products_from_page(page, limit=10, category_hint="Men's Casual Shoes", search_url=target_url, visited_urls=set())

    print("\n----------------------------------------")
    print("STATE EVALUATION:")
    if is_valid and len(candidate_products) > 0:
        print("STATE: A (Amazon loaded with products)")
        print(f"Products extracted: {len(candidate_products)}")
        for idx, p in enumerate(candidate_products[:5], 1):
            print(f"  {idx}. ASIN: {p['asin']} | Title: {p['product_title'][:50]}")
    elif is_valid and is_legitimate_zero_results(page, html_content):
        print("STATE: B (Amazon loaded with zero products - NO_PRODUCTS)")
        print("Products extracted: 0")
    else:
        print("STATE: C (Navigation failed)")
        print(f"Reason: {valid_reason if not is_valid else 'Zero products found without legitimate zero-results markers'}")
    print("----------------------------------------")

    bm.close()

if __name__ == "__main__":
    run_diagnostic()
