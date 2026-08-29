import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.repository import SellerRepository
from database.database import init_db
from main import process_category_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def test_single_category():
    category_name = "Men's Casual Shoes"
    target_url = "https://www.amazon.in/s?k=Men%27s+Casual+Shoes"
    
    print("==================================================")
    print("RUNNING SINGLE CATEGORY LIFECYCLE TEST")
    print(f"Category: {category_name}")
    print(f"URL: {target_url}")
    print("==================================================")

    init_db("amazon_sellers.db")
    repo = SellerRepository("amazon_sellers.db")
    
    test_config = {
        "product_limit": 2,
        "top_businesses": 5,
        "max_pages": 1,
        "max_sellers_per_product": 5,
        "max_category_runtime_minutes": 10
    }

    res = process_category_run(
        category_name=category_name,
        target_url=target_url,
        config=test_config,
        repo=repo,
        headless=True,
        allow_reprocess=True,
        is_batch=False
    )

    print("\n==================================================")
    print("CATEGORY EXECUTION RESULT:")
    print(f"Status: {res.get('status')}")
    print(f"Category: {res.get('category')}")
    print(f"Sellers Count: {res.get('sellers_count')}")
    print(f"Added Count: {res.get('added_count')}")
    print("==================================================")

    assert res.get("status") in ("COMPLETED", "SUCCESS"), f"Expected success status, got {res.get('status')}"

if __name__ == "__main__":
    test_single_category()
