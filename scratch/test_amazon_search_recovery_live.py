import time
import re
from playwright.sync_api import sync_playwright

test_categories = [
    ("Men's Casual Shoes", "https://www.amazon.in/s?k=Men%27s+Casual+Shoes"),
    ("Men's Sports Shoes", "https://www.amazon.in/s?k=Men%27s+Sports+Shoes"),
    ("Men's Formal Shoes", "https://www.amazon.in/s?k=Men%27s+Formal+Shoes"),
    ("Men's Sandals & Floaters", "https://www.amazon.in/s?k=Men%27s+Sandals+%26+Floaters")
]

print("==================================================")
print("TESTING AMAZON SEARCH RECOVERY PIPELINE (LIVE)")
print("==================================================")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
    )
    context = browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        locale="en-IN"
    )
    page = context.new_page()

    for cat_name, cat_url in test_categories:
        print(f"\n========================================")
        print(f"TESTING CATEGORY: {cat_name}")
        print(f"URL: {cat_url}")
        print(f"========================================")

        products = []
        visited_asins = set()

        # Step 1: Try page.goto
        nav_error = None
        try:
            resp = page.goto(cat_url, wait_until="commit", timeout=20000)
        except Exception as e:
            nav_error = str(e)
            print(f"page.goto exception: {nav_error}")

        # Step 2: In-page settle & inspect
        time.sleep(1)
        cur_url = page.url
        title = page.title()
        html = page.content()
        print(f"Current URL: {cur_url}")
        print(f"Page title: {title}")
        print(f"HTML length: {len(html)}")

        links = page.query_selector_all("a[href*='/dp/']")
        print(f"Product selectors in DOM: {len(links)}")

        if len(links) == 0:
            print("No links in DOM, trying context.request.get fallback...")
            req_resp = context.request.get(
                cat_url,
                headers={
                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "accept-language": "en-IN,en-GB;q=0.9,en;q=0.8",
                    "referer": "https://www.amazon.in/"
                },
                timeout=25000
            )
            print(f"context.request status: {req_resp.status}")
            req_html = req_resp.text()
            print(f"context.request HTML length: {len(req_html)}")
            page.set_content(req_html, wait_until="domcontentloaded")
            links = page.query_selector_all("a[href*='/dp/']")
            print(f"Product selectors after set_content: {len(links)}")

        for link in links:
            if len(products) >= 10:
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
                if asin in visited_asins:
                    continue
                visited_asins.add(asin)
                title_text = link.inner_text().strip() or f"Amazon Product {asin}"
                products.append({
                    "asin": asin,
                    "product_url": f"https://www.amazon.in/dp/{asin}",
                    "product_title": title_text[:100],
                    "category": cat_name
                })
            except Exception:
                continue

        print(f"\nPRODUCT DISCOVERY RESULT:")
        print(f"Category: {cat_name}")
        print(f"Products extracted: {len(products)}")
        assert len(products) > 0, f"Failed to extract products for {cat_name}"
        print(f"Sample product 1: ASIN={products[0]['asin']}, Title={products[0]['product_title']}")

    context.close()
    browser.close()

print("\n==================================================")
print("ALL 4 CATEGORIES TESTED AND PASSED SUCCESSFULLY!")
print("==================================================")
