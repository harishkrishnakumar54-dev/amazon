import re
from urllib.parse import urlparse
from typing import Tuple, Optional
import logging

logger = logging.getLogger("amazon_scraper")

def normalize_amazon_url(raw_url: str) -> str:
    """
    Normalizes any raw URL or input line into a clean HTTP/HTTPS Amazon URL.

    Requirements:
    1. Strip whitespace.
    2. Detect Markdown links: [display text](actual_url).
    3. Extract the href from markdown link.
    4. Remove surrounding quotes ('...' or "...").
    5. Remove accidental backticks (`...`).
    6. Remove trailing whitespace.
    7. Return ONLY the actual HTTP/HTTPS URL.
    8. Preserve existing Amazon query strings and encoding (e.g. Men%27s+Shoes).
    """
    if not raw_url:
        return ""
    u = str(raw_url).strip()

    # Step 1, 4, 5: Repeatedly strip surrounding whitespace, quotes, and backticks
    changed = True
    while changed:
        old = u
        u = u.strip().strip("'\"`").strip()
        changed = (u != old)

    # Step 2 & 3: Detect Markdown link syntax and extract actual href
    md_match = re.search(r'\[.*?\]\((https?://[^\s\)]+)\)', u)
    if md_match:
        u = md_match.group(1)
    elif u.startswith("[") and "](" in u:
        parts = u.split("](", 1)
        href = parts[1]
        if href.endswith(")"):
            href = href[:-1]
        u = href
    elif u.startswith("<") and u.endswith(">"):
        u = u[1:-1]

    # Step 4, 5, 6: Strip surrounding quotes and backticks again
    changed = True
    while changed:
        old = u
        u = u.strip().strip("'\"`").strip()
        changed = (u != old)

    # Clean accidental trailing unmatched brackets/parentheses
    if u.endswith(")") and "(" not in u:
        u = u[:-1].rstrip()
    if u.endswith("]") and "[" not in u:
        u = u[:-1].rstrip()

    return u.strip()

def validate_amazon_url(url: str) -> bool:
    """
    Validates that the given URL has a valid scheme ('http' or 'https') and netloc.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
        return bool(parsed.scheme in ("http", "https") and parsed.netloc)
    except Exception:
        return False

def prepare_navigation_url(raw_url: str, log_obj: Optional[logging.Logger] = None) -> Tuple[bool, str]:
    """
    Prepares a URL for Playwright navigation by:
    1. Normalizing raw_url (stripping markdown, quotes, backticks, whitespace).
    2. Validating scheme and netloc.
    3. Logging exact validation status:
       Raw URL:
       <original value>

       Normalized URL:
       <clean URL>

       URL valid:
       YES / NO

    4. If invalid: logs and prints 'INVALID AMAZON URL'.
    Returns (is_valid, normalized_url).
    """
    normalized_url = normalize_amazon_url(raw_url)
    is_valid = validate_amazon_url(normalized_url)

    print(f"Raw URL:\n{raw_url}\n")
    print(f"Normalized URL:\n{normalized_url}\n")
    print(f"URL valid:\n{'YES' if is_valid else 'NO'}\n")

    if not is_valid:
        print("INVALID AMAZON URL\n")
        active_logger = log_obj or logger
        active_logger.error(f"INVALID AMAZON URL: Raw='{raw_url}', Normalized='{normalized_url}'")

    return is_valid, normalized_url
