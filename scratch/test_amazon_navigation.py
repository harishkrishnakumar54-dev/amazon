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
    check_amazon_block,
    verify_amazon_search_page
)
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

def run_amazon_navigation_tests():
    print("==================================================")
    print("RUNNING AMAZON NAVIGATION & DOWNLOAD TEST SUITE")
    print("==================================================")

    # -------------------------------------------------------------
    # TEST 1: Page.goto: Download is starting on all 3 attempts
    # -------------------------------------------------------------
    print("\n--- TEST 1: Download is starting Error Detection & 3 Retries ---")
    mock_page = MagicMock()
    mock_page.goto.side_effect = Exception("Page.goto: Download is starting")

    mock_bm = MagicMock()
    fresh_page = MagicMock()
    fresh_page.goto.side_effect = Exception("Page.goto: Download is starting")
    mock_bm.new_page.return_value = fresh_page

    scraper = AmazonSearchScraper(mock_page, max_retries=3, browser_mgr=mock_bm)

    with patch("time.sleep") as mock_sleep:
        try:
            scraper.discover_products(
                "https://www.amazon.in/s?k=mens+casual+shoes",
                limit=5,
                category_name="Men's Casual Shoes"
            )
            assert False, "Should have raised AmazonNavigationException after 3 failed attempts"
        except AmazonNavigationException as ane:
            print(f"PASS: Correctly raised AmazonNavigationException: {ane}")
            assert "Download is starting" in ane.reason, f"Expected Download is starting in reason, got {ane.reason}"
            assert mock_sleep.call_count == 2, f"Expected 2 backoff sleep calls (2s, 5s), got {mock_sleep.call_count}"
            assert mock_bm.new_page.call_count == 2, f"Expected 2 fresh page calls, got {mock_bm.new_page.call_count}"
            print("PASS: Verified 3 retries, fresh context recreation, and final AmazonNavigationException.")

    # -------------------------------------------------------------
    # TEST 2: Download is starting on Attempt 1, Success on Attempt 2
    # -------------------------------------------------------------
    print("\n--- TEST 2: Download on Attempt 1, Clean Recovery on Attempt 2 ---")
    mock_page_1 = MagicMock()
    mock_page_1.goto.side_effect = Exception("Page.goto: Download is starting")

    mock_page_2 = MagicMock()
    mock_resp_2 = MagicMock()
    mock_resp_2.status = 200
    mock_resp_2.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp_2.url = "https://www.amazon.in/s?k=mens+casual+shoes"
    mock_page_2.goto.return_value = mock_resp_2
    mock_page_2.title.return_value = "Amazon.in: Men's Casual Shoes"
    mock_page_2.url = "https://www.amazon.in/s?k=mens+casual+shoes"
    
    mock_link = MagicMock()
    mock_link.get_attribute.return_value = "/dp/B001234567"
    mock_link.inner_text.return_value = "Men's Sneaker Shoe"
    mock_page_2.query_selector_all.return_value = [mock_link]
    mock_page_2.query_selector.return_value = MagicMock() # Selector found

    mock_bm = MagicMock()
    mock_bm.new_page.return_value = mock_page_2

    scraper = AmazonSearchScraper(mock_page_1, max_retries=3, browser_mgr=mock_bm)

    with patch("time.sleep") as mock_sleep:
        products = scraper.discover_products(
            "https://www.amazon.in/s?k=mens+casual+shoes",
            limit=5,
            category_name="Men's Casual Shoes"
        )
        assert len(products) == 1, f"Expected 1 product discovered, got {len(products)}"
        assert products[0]["asin"] == "B001234567"
        assert products[0]["category"] == "Men's Casual Shoes"
        assert mock_sleep.call_count == 1, f"Expected 1 backoff sleep call, got {mock_sleep.call_count}"
        print(f"PASS: Successfully recovered on attempt 2, extracted product ASIN: {products[0]['asin']}")

    # -------------------------------------------------------------
    # TEST 3: Non-HTML Content-Type (octet-stream) Detection
    # -------------------------------------------------------------
    print("\n--- TEST 3: Non-HTML Content-Type Detection & Retry ---")
    mock_page_binary = MagicMock()
    mock_resp_binary = MagicMock()
    mock_resp_binary.status = 200
    mock_resp_binary.headers = {"content-type": "application/octet-stream"}
    mock_resp_binary.url = "https://www.amazon.in/s?k=test"
    mock_page_binary.goto.return_value = mock_resp_binary

    scraper = AmazonSearchScraper(mock_page_binary, max_retries=3)
    with patch("time.sleep") as mock_sleep:
        try:
            scraper.discover_products("https://www.amazon.in/s?k=test", limit=5)
            assert False, "Should have raised AmazonNavigationException for binary response"
        except AmazonNavigationException as ane:
            print(f"PASS: Correctly rejected binary content-type: {ane}")
            assert mock_sleep.call_count == 2
            print("PASS: Verified Non-HTML Content-Type was detected and rejected across 3 retries.")

    # -------------------------------------------------------------
    # TEST 4: Verified Amazon HTML Page with 0 Products (NO_PRODUCTS)
    # -------------------------------------------------------------
    print("\n--- TEST 4: NO_PRODUCTS Only When Amazon Successfully Loaded ---")
    mock_page_empty = MagicMock()
    mock_resp_empty = MagicMock()
    mock_resp_empty.status = 200
    mock_resp_empty.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp_empty.url = "https://www.amazon.in/s?k=nonexistentitemxyz123"
    mock_page_empty.goto.return_value = mock_resp_empty
    mock_page_empty.title.return_value = "Amazon.in : nonexistentitemxyz123"
    mock_page_empty.url = "https://www.amazon.in/s?k=nonexistentitemxyz123"
    mock_page_empty.content.return_value = "<html><body>No results for nonexistentitemxyz123. Try checking your spelling.</body></html>"
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

    scraper = AmazonSearchScraper(mock_page_503, max_retries=3)
    with patch("time.sleep") as mock_sleep:
        try:
            scraper.discover_products("https://www.amazon.in/s?k=test", limit=5)
            assert False, "Should have raised AmazonBlockedException on 503"
        except AmazonBlockedException as abe:
            print(f"PASS: Correctly raised AmazonBlockedException: {abe}")
            assert mock_sleep.call_count == 2
            print("PASS: Verified 3 retries on 503 block.")

    print("\n==================================================")
    print("ALL AMAZON NAVIGATION TESTS PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    run_amazon_navigation_tests()
