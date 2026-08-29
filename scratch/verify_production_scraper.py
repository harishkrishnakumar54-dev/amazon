import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.browser import BrowserManager
from scraper.amazon_search import AmazonSearchScraper

categories = [
    ("Men's Casual Shoes", "https://www.amazon.in/s?k=Men%27s+Casual+Shoes"),
    ("Men's Sports Shoes", "https://www.amazon.in/s?k=Men%27s+Sports+Shoes"),
    ("Men's Formal Shoes", "https://www.amazon.in/s?k=Men%27s+Formal+Shoes"),
    ("Men's Sandals & Floaters", "https://www.amazon.in/s?k=Men%27s+Sandals+%26+Floaters")
]

print("==================================================")
print("VERIFYING PRODUCTION AMAZON SEARCH SCRAPER")
print("==================================================")

bm = BrowserManager(headless=True)
bm.start()
page = bm.new_page()
scraper = AmazonSearchScraper(page, max_retries=3, browser_mgr=bm)

total_extracted = {}

for cat_name, cat_url in categories:
    print(f"\n==================================================")
    print(f"RUNNING CATEGORY: {cat_name}")
    print(f"URL: {cat_url}")
    print(f"==================================================")

    products = scraper.discover_products(cat_url, limit=5, category_name=cat_name)
    total_extracted[cat_name] = len(products)
    print(f"\n>>> RESULT FOR {cat_name}: {len(products)} products discovered")
    if products:
        for idx, p in enumerate(products, 1):
            print(f"  {idx}. ASIN: {p['asin']} | Title: {p['product_title'][:60]}")

bm.close()

print("\n==================================================")
print("SUMMARY OF ALL 4 CATEGORIES:")
for cat_name, cnt in total_extracted.items():
    print(f" - {cat_name}: {cnt} products (Status: {'SUCCESS' if cnt > 0 else 'FAILED'})")
print("==================================================")

assert all(cnt > 0 for cnt in total_extracted.values()), "All categories must have products > 0"
