import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.amazon_search import (
    AmazonSearchScraper,
    AmazonBlockedException,
    AmazonNavigationException,
    AmazonNavigationResult,
    check_amazon_block,
    is_valid_amazon_html,
    is_legitimate_zero_results
)
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

def run_amazon_navigation_tests():
    print("==================================================")
    print("RUNNING AMAZON NAVIGATION & DOWNLOAD TEST SUITE")
    print("==================================================")

    # -------------------------------------------------------------
    # TEST 1: chrome-error:// MUST FAIL AND NEVER REPORT NO_PRODUCTS
    # -------------------------------------------------------------
    print("\n--- TEST 1: chrome-error:// MUST FAIL AND NEVER REPORT NO_PRODUCTS ---")
    mock_page = MagicMock()
    mock_page.goto.side_effect = Exception("Page.goto: Download is starting")
    mock_page.url = "chrome-error://chromewebdata/"
    mock_page.title.return_value = ""
    mock_page.content.return_value = "<html><body></body></html>"
    mock_page.query_selector.return_value = None
    mock_page.query_selector_all.return_value = []
    mock_page.context.request.get.side_effect = Exception("Context request failed")

    mock_bm = MagicMock()
    fresh_page = MagicMock()
    fresh_page.goto.side_effect = Exception("Page.goto: Download is starting")
    fresh_page.url = "chrome-error://chromewebdata/"
    fresh_page.title.return_value = ""
    fresh_page.content.return_value = "<html><body></body></html>"
    fresh_page.query_selector.return_value = None
    fresh_page.query_selector_all.return_value = []
    fresh_page.context.request.get.side_effect = Exception("Context request failed")
    mock_bm.new_page.return_value = fresh_page

    scraper = AmazonSearchScraper(mock_page, max_retries=3, browser_mgr=mock_bm)

    with patch("time.sleep") as mock_sleep, patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = Exception("HTTP Fallback failed")
        try:
            scraper.discover_products(
                "https://www.amazon.in/s?k=Men%27s+Casual+Shoes",
                limit=5,
                category_name="Men's Casual Shoes"
            )
            assert False, "Should have raised AmazonNavigationException for chrome-error://, NEVER return empty list"
        except AmazonNavigationException as ane:
            print(f"PASS: Correctly raised AmazonNavigationException: {ane}")
            assert "chrome-error" in ane.reason or "Download is starting" in ane.reason or "Navigation Error" in ane.reason
            assert mock_sleep.call_count >= 2, f"Expected backoff sleep calls, got {mock_sleep.call_count}"
            print("PASS: Verified chrome-error:// was treated as NAVIGATION_FAILURE and raised AmazonNavigationException.")

    # -------------------------------------------------------------
    # TEST 2: goto Download Error -> Recovery via Context Request
    # -------------------------------------------------------------
    print("\n--- TEST 2: goto Download Error -> Recovery via Context Request ---")
    mock_page_rec = MagicMock()
    mock_page_rec.goto.side_effect = Exception("Page.goto: Download is starting")
    mock_page_rec.url = "chrome-error://chromewebdata/"
    mock_page_rec.title.return_value = ""
    mock_page_rec.content.return_value = ""
    mock_page_rec.query_selector.return_value = MagicMock()
    
    mock_ctx_resp = MagicMock()
    mock_ctx_resp.status = 200
    mock_ctx_resp.headers = {"content-type": "text/html"}
    mock_ctx_resp.text.return_value = "<html><head><title>Amazon.in: Men's Casual Shoes</title></head><body><div class='s-search-results'><div data-asin='B09PVFJ2P4'><a href='/dp/B09PVFJ2P4'>Sparx Shoe</a></div></div></body></html>"
    mock_page_rec.context.request.get.return_value = mock_ctx_resp

    mock_link = MagicMock()
    mock_link.get_attribute.return_value = "/dp/B09PVFJ2P4"
    mock_link.inner_text.return_value = "Sparx Shoe SM-734"
    mock_page_rec.query_selector_all.return_value = [mock_link]

    scraper = AmazonSearchScraper(mock_page_rec, max_retries=3)

    with patch("time.sleep"):
        products = scraper.discover_products(
            "https://www.amazon.in/s?k=Men%27s+Casual+Shoes",
            limit=5,
            category_name="Men's Casual Shoes"
        )
        assert len(products) == 1, f"Expected 1 product discovered, got {len(products)}"
        assert products[0]["asin"] == "B09PVFJ2P4"
        assert products[0]["category"] == "Men's Casual Shoes"
        print(f"PASS: Successfully recovered via context.request, extracted ASIN: {products[0]['asin']}")

    # -------------------------------------------------------------
    # TEST 3: Direct goto Success
    # -------------------------------------------------------------
    print("\n--- TEST 3: Direct goto Success ---")
    mock_page_direct = MagicMock()
    mock_resp_direct = MagicMock()
    mock_resp_direct.status = 200
    mock_resp_direct.headers = {"content-type": "text/html; charset=utf-8"}
    mock_page_direct.goto.return_value = mock_resp_direct
    mock_page_direct.title.return_value = "Amazon.in: Men's Sports Shoes"
    mock_page_direct.url = "https://www.amazon.in/s?k=Men%27s+Sports+Shoes"
    mock_page_direct.content.return_value = "<html><head><title>Amazon.in: Men's Sports Shoes</title></head><body><div class='s-main-slot' data-asin='B01MRN1BY4'><a href='/dp/B01MRN1BY4'>Shoes</a></div></body></html>"
    
    mock_link_sports = MagicMock()
    mock_link_sports.get_attribute.return_value = "/dp/B01MRN1BY4"
    mock_link_sports.inner_text.return_value = "Men's Sports Running Shoes"
    mock_page_direct.query_selector_all.return_value = [mock_link_sports]
    mock_page_direct.query_selector.return_value = MagicMock()

    scraper = AmazonSearchScraper(mock_page_direct, max_retries=3)
    products = scraper.discover_products(
        "https://www.amazon.in/s?k=Men%27s+Sports+Shoes",
        limit=5,
        category_name="Men's Sports Shoes"
    )
    assert len(products) == 1
    assert products[0]["asin"] == "B01MRN1BY4"
    print(f"PASS: Direct navigation succeeded, extracted ASIN: {products[0]['asin']}")

    # -------------------------------------------------------------
    # TEST 4: Verified Amazon HTML Page with 0 Products (NO_PRODUCTS)
    # -------------------------------------------------------------
    print("\n--- TEST 4: NO_PRODUCTS Only When Amazon Successfully Loaded ---")
    mock_page_empty = MagicMock()
    mock_resp_empty = MagicMock()
    mock_resp_empty.status = 200
    mock_resp_empty.headers = {"content-type": "text/html; charset=utf-8"}
    mock_page_empty.goto.return_value = mock_resp_empty
    mock_page_empty.title.return_value = "Amazon.in : nonexistentitemxyz123"
    mock_page_empty.url = "https://www.amazon.in/s?k=nonexistentitemxyz123"
    mock_page_empty.content.return_value = "<html><head><title>Amazon.in : nonexistentitemxyz123</title></head><body><div class='nav-logo'>Amazon</div><div>No results for nonexistentitemxyz123. Try checking your spelling or use more general terms.</div></body></html>"
    mock_page_empty.query_selector_all.return_value = []
    mock_page_empty.query_selector.return_value = None

    scraper = AmazonSearchScraper(mock_page_empty, max_retries=3)
    products = scraper.discover_products("https://www.amazon.in/s?k=nonexistentitemxyz123", limit=5)
    assert products == [], f"Expected empty product list on verified zero results page, got {products}"
    print("PASS: Verified NO_PRODUCTS returned cleanly when page was verified Amazon zero-results page.")

    # -------------------------------------------------------------
    # TEST 5: Amazon Block (503) Handled Cleanly
    # -------------------------------------------------------------
    print("\n--- TEST 5: Amazon 503 Block Detection ---")
    mock_page_503 = MagicMock()
    mock_resp_503 = MagicMock()
    mock_resp_503.status = 503
    mock_resp_503.headers = {"content-type": "text/html"}
    mock_page_503.goto.return_value = mock_resp_503
    mock_page_503.title.return_value = "503 - Service Unavailable"
    mock_page_503.url = "https://www.amazon.in/s?k=test"
    mock_page_503.content.return_value = "<html><title>503 - Service Unavailable</title><body>503 Service Unavailable</body></html>"

    scraper = AmazonSearchScraper(mock_page_503, max_retries=3)
    with patch("time.sleep") as mock_sleep:
        try:
            scraper.discover_products("https://www.amazon.in/s?k=test", limit=5)
            assert False, "Should have raised AmazonBlockedException on 503"
        except AmazonBlockedException as abe:
            print(f"PASS: Correctly raised AmazonBlockedException: {abe}")
            assert mock_sleep.call_count >= 2
            print("PASS: Verified 3 retries on 503 block.")

    print("\n==================================================")
    print("ALL AMAZON NAVIGATION TESTS PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    run_amazon_navigation_tests()
