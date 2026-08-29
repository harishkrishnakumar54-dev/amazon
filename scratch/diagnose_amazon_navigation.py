import time
import urllib.request
import gzip
import io
import re
from playwright.sync_api import sync_playwright

url = "https://www.amazon.in/s?k=Men%27s+Casual+Shoes"
print(f"Target URL: {url}")

print("\n--- 1. Testing with Playwright Chromium (Headless=True) ---")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    context = browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        locale="en-IN"
    )
    page = context.new_page()

    download_event_triggered = []
    def on_download(download):
        download_event_triggered.append(download)
        print(f"DOWNLOAD EVENT TRIGGERED: url={download.url}, suggested_filename={download.suggested_filename}")

    page.on("download", on_download)

    try:
        resp = page.goto(url, wait_until="commit", timeout=30000)
        print(f"goto result: status={resp.status if resp else 'None'}, url={resp.url if resp else 'None'}")
        if resp:
            print(f"Headers: {dict(resp.headers)}")
    except Exception as e:
        print(f"goto exception: {type(e).__name__}: {e}")

    time.sleep(2)
    print(f"Current page URL: {page.url}")
    try:
        print(f"Page title: {page.title()}")
        html = page.content()
        print(f"HTML length: {len(html)}")
        links = page.query_selector_all("a[href*='/dp/']")
        print(f"Product /dp/ links found in DOM: {len(links)}")
        if len(links) > 0:
            print(f"First link href: {links[0].get_attribute('href')}")
    except Exception as pe:
        print(f"Error inspecting page: {pe}")

    context.close()
    browser.close()

print("\n--- 2. Testing with Python urllib.request ---")
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.amazon.in/",
    "Connection": "keep-alive"
}
try:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        print(f"HTTP status: {resp.status}")
        print(f"Content-Type: {resp.headers.get('Content-Type')}")
        raw_data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            html_text = gzip.decompress(raw_data).decode("utf-8", errors="replace")
        else:
            html_text = raw_data.decode("utf-8", errors="replace")
        print(f"Response HTML length: {len(html_text)}")
        asins = re.findall(r"/dp/([A-Z0-9]{10})", html_text)
        print(f"Unique ASINs extracted from HTTP response: {len(set(asins))}")
except Exception as req_err:
    print(f"HTTP request error: {req_err}")
