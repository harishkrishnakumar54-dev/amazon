import time
import re
import urllib.request
import gzip
from playwright.sync_api import sync_playwright

url = "https://www.amazon.in/s?k=Men%27s+Casual+Shoes"
print(f"Testing recovery strategies for: {url}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    context = browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        locale="en-IN"
    )
    page = context.new_page()

    print("\n--- Testing Playwright context.request.get() ---")
    try:
        req_resp = context.request.get(
            url,
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "accept-language": "en-IN,en-GB;q=0.9,en;q=0.8",
                "referer": "https://www.amazon.in/"
            },
            timeout=30000
        )
        print(f"context.request status: {req_resp.status}")
        print(f"context.request headers: {req_resp.headers.get('content-type')}")
        html = req_resp.text()
        print(f"context.request HTML length: {len(html)}")
        asins = re.findall(r"/dp/([A-Z0-9]{10})", html)
        print(f"Extracted unique ASINs via context.request: {len(set(asins))}")
    except Exception as e:
        print(f"context.request error: {e}")

    context.close()
    browser.close()
