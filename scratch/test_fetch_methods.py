import sys
import gzip
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.browser import BrowserManager
from scraper.amazon_search import extract_products_from_page

def test_fetch_methods():
    target_url = "https://www.amazon.in/s?k=Men%27s+Casual+Shoes"
    bm = BrowserManager(headless=True)
    bm.start()
    page = bm.new_page()

    print("--- Testing context.request.get ---")
    ctx_resp = page.context.request.get(
        target_url,
        headers={
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "accept-language": "en-IN,en-GB;q=0.9,en;q=0.8",
            "referer": "https://www.amazon.in/"
        }
    )
    print(f"Context request status: {ctx_resp.status}")
    ctx_text = ctx_resp.text()
    print(f"Context request text length: {len(ctx_text)}")
    
    page.set_content(ctx_text, wait_until="domcontentloaded")
    print(f"Page title after set_content: {page.title()}")
    
    prods = extract_products_from_page(page, limit=10, category_hint="Men's Casual Shoes", search_url=target_url, visited_urls=set())
    print(f"Extracted products from set_content: {len(prods)}")
    for p in prods[:3]:
        print(f"  ASIN: {p['asin']} | Title: {p['product_title'][:50]}")

    bm.close()

if __name__ == "__main__":
    test_fetch_methods()
