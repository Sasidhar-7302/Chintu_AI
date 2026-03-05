"""Deal Finder capability: compare prices across vendors with robust, non-browser scraping.

Why this exists:
- `browser_pilot` is great for general automation but can be impacted by anti-bot
  measures on shopping sites (Amazon/Newegg).
- For price comparison we can do better by using deterministic parsing of search
  result pages (read-only) and returning structured evidence.

Safety:
- Read-only. Never proceeds to checkout or payment.
- Makes a small number of requests and returns links + prices.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

from pydantic import BaseModel, Field

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType

logger = logging.getLogger(__name__)

_VENDOR_DOMAINS: Dict[str, str] = {
    "amazon": "amazon.com",
    "newegg": "newegg.com",
    "bestbuy": "bestbuy.com",
    "walmart": "walmart.com",
    "bhphoto": "bhphotovideo.com",
    "microcenter": "microcenter.com",
}

# Extra "web" allowlist entries (we'll only compare deals from these).
_TRUSTED_WEB_DOMAINS: List[str] = sorted(
    set(_VENDOR_DOMAINS.values())
    | {
        "adorama.com",
        "target.com",
        "costco.com",
        "lenovo.com",
        "dell.com",
        "hp.com",
        "samsung.com",
    }
)


def _normalize_domain(url_or_domain: str) -> str:
    raw = str(url_or_domain or "").strip().lower()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        netloc = parsed.netloc or parsed.path  # allow passing just a domain
    except Exception:
        netloc = raw
    netloc = netloc.split("@")[-1]
    netloc = netloc.split(":")[0]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc.strip(".")


def _domain_allowed(domain: str, allowed: List[str]) -> bool:
    d = _normalize_domain(domain)
    if not d:
        return False
    for a in allowed or []:
        a2 = _normalize_domain(a)
        if not a2:
            continue
        if d == a2 or d.endswith("." + a2):
            return True
    return False


class DealFinderSchema(BaseModel):
    query: str = Field(..., description="Item to search for (e.g., '2TB NVMe SSD').")
    comparison_products: Optional[List[str]] = Field(
        default=None,
        description="Optional explicit list of products to compare (e.g., ['RTX 4060', 'RX 7600']).",
    )
    vendors: List[str] = Field(
        default_factory=lambda: ["amazon", "newegg", "bestbuy", "bhphoto", "microcenter", "walmart"],
        description="Vendors to compare (subset of: amazon, newegg, bestbuy, bhphoto, microcenter, walmart, web).",
    )
    max_results_per_vendor: int = Field(6, ge=1, le=20, description="Max results to extract per vendor.")
    include_web_search: bool = Field(
        False,
        description=(
            "If true, also search additional trusted retailers via DuckDuckGo and parse product JSON-LD prices. "
            "This increases coverage but may be slower."
        ),
    )
    max_web_results: int = Field(8, ge=1, le=25, description="Max web results to inspect when include_web_search=true.")


@dataclass(frozen=True)
class DealListing:
    vendor: str
    title: str
    price: Optional[float]
    shipping: Optional[float]
    url: str
    meta: Dict[str, Any]

    @property
    def total(self) -> Optional[float]:
        if self.price is None:
            return None
        if self.shipping is None:
            return float(self.price)
        return float(self.price) + float(self.shipping)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vendor": self.vendor,
            "title": self.title,
            "price": self.price,
            "shipping": self.shipping,
            "total": self.total,
            "url": self.url,
            "meta": self.meta,
        }


def _headers() -> Dict[str, str]:
    # A boring, stable UA string. We keep requests minimal and deterministic.
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }


def _fetch_html_requests(url: str, *, timeout_s: int = 20) -> Tuple[str, int, str]:
    """Fetch HTML via Requests (best-effort). Returns (html, status_code, err)."""
    try:
        import requests
    except Exception as exc:  # noqa: BLE001
        return "", 0, f"requests missing: {exc}"
    try:
        resp = requests.get(str(url), headers=_headers(), timeout=max(5, int(timeout_s)), allow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        return "", 0, f"request failed: {exc}"
    html = resp.text or ""
    return html, int(getattr(resp, "status_code", 0) or 0), ""


def _status_retryable(status_code: int) -> bool:
    code = int(status_code or 0)
    if code <= 0:
        return False
    return code in {403, 408, 409, 425, 429, 500, 502, 503, 504}


def _fetch_with_requests_retries(url: str, *, timeout_s: int = 20, max_attempts: int = 2):
    """Best-effort request with bounded retries for transient HTTP/network failures."""
    try:
        import requests
    except Exception as exc:  # noqa: BLE001
        return None, f"requests missing: {exc}"

    attempts = max(1, int(max_attempts or 1))
    last_error = ""
    for attempt in range(attempts):
        try:
            resp = requests.get(
                str(url),
                headers=_headers(),
                timeout=max(5, int(timeout_s)),
                allow_redirects=True,
            )
            status = int(getattr(resp, "status_code", 0) or 0)
            if _status_retryable(status) and attempt < attempts - 1:
                time.sleep(0.4 * (attempt + 1))
                continue
            return resp, ""
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            if attempt < attempts - 1:
                time.sleep(0.4 * (attempt + 1))
                continue
            break
    return None, (last_error or "request failed")


def _looks_blocked_generic(html: str) -> bool:
    low = (html or "").lower()
    return any(
        s in low
        for s in [
            "access denied",
            "request blocked",
            "unusual traffic",
            "verify you are a human",
            "are you a robot",
            "captcha",
        ]
    )


def _parse_money(value: str) -> Optional[float]:
    raw = str(value or "").strip()
    if not raw:
        return None
    # Common forms: "$199.99", "199.99", "$1,299.00"
    raw = raw.replace(",", "")
    m = re.search(r"(-?\d+(?:\.\d{1,2})?)", raw)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _extract_jsonld_blocks(html: str) -> List[Any]:
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    blocks: List[Any] = []
    for tag in soup.find_all("script"):
        try:
            if (tag.get("type") or "").strip().lower() != "application/ld+json":
                continue
            raw = tag.string or tag.get_text() or ""
            raw = raw.strip()
            if not raw:
                continue
            data = json.loads(raw)
            blocks.append(data)
        except Exception:
            continue
    return blocks


def _iter_jsonld_objects(value: Any) -> List[Dict[str, Any]]:
    """Flatten a JSON-LD payload into a list of dict objects."""
    out: List[Dict[str, Any]] = []
    if isinstance(value, dict):
        out.append(value)
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                if isinstance(item, dict):
                    out.append(item)
        return out
    if isinstance(value, list):
        for item in value:
            out.extend(_iter_jsonld_objects(item))
    return out


def _jsonld_type(obj: Dict[str, Any]) -> List[str]:
    t = obj.get("@type")
    if isinstance(t, str):
        return [t]
    if isinstance(t, list):
        return [str(x) for x in t if x]
    return []


def _coerce_abs_url(url: str, *, base: str = "") -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        if base:
            return base.rstrip("/") + u
    return u


def _extract_products_from_jsonld(html: str, *, base_url: str = "", max_results: int = 8) -> List[Tuple[str, Optional[float], str]]:
    """Return [(title, price, url)] from JSON-LD (best-effort)."""
    items: List[Tuple[str, Optional[float], str]] = []
    for block in _extract_jsonld_blocks(html):
        for obj in _iter_jsonld_objects(block):
            types = {t.lower() for t in _jsonld_type(obj)}

            # ItemList -> itemListElement
            if "itemlist" in types:
                els = obj.get("itemListElement")
                if isinstance(els, list):
                    for el in els:
                        if not isinstance(el, dict):
                            continue
                        it = el.get("item") if isinstance(el.get("item"), dict) else el
                        if not isinstance(it, dict):
                            continue
                        name = str(it.get("name") or it.get("title") or "").strip()
                        url = str(it.get("url") or "").strip()
                        if not name or not url:
                            continue
                        items.append((name, None, _coerce_abs_url(url, base=base_url)))
                        if len(items) >= max(1, int(max_results)):
                            return items
                continue

            # Product
            if "product" not in types:
                continue
            name = str(obj.get("name") or obj.get("title") or "").strip()
            url = str(obj.get("url") or "").strip()

            offers = obj.get("offers")
            offer_obj = offers[0] if isinstance(offers, list) and offers else offers
            price = None
            offer_url = ""
            if isinstance(offer_obj, dict):
                price = _parse_money(str(offer_obj.get("price") or offer_obj.get("lowPrice") or offer_obj.get("highPrice") or ""))
                offer_url = str(offer_obj.get("url") or "").strip()

            final_url = _coerce_abs_url(offer_url or url, base=base_url)
            if not name or not final_url:
                continue
            items.append((name, price, final_url))
            if len(items) >= max(1, int(max_results)):
                return items
    return items


def _looks_blocked_amazon(html: str) -> bool:
    low = (html or "").lower()
    return any(
        s in low
        for s in [
            "robot check",
            "/errors/validatecaptcha",
            "enter the characters you see below",
            "sorry, we just need to make sure you're not a robot",
            "captcha",
        ]
    )


def _looks_blocked_newegg(html: str) -> bool:
    low = (html or "").lower()
    return any(
        s in low
        for s in [
            "access denied",
            "request blocked",
            "unusual traffic",
            "captcha",
        ]
    )


def _extract_query(text: str) -> str:
    """Best-effort extraction of the item query from free-form text."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()

    # Patterns like: "I need a new X. Find the best price ..."
    m = re.search(r"\bneed a new\b\s+(.+?)(?:\.|\n|find the best price|compare|$)", lowered, flags=re.IGNORECASE)
    if m:
        return raw[m.start(1) : m.end(1)].strip(" .,:;\"'")

    # Patterns like: "find the best price for X"
    m = re.search(r"\b(best price|find the best price)\b\s+(?:for|on)\s+(.+)", lowered, flags=re.IGNORECASE)
    if m:
        q = raw[m.start(2) :].strip()
        # Remove trailing vendor instructions.
        q = re.sub(
            r"\b(on amazon|on newegg|on best buy|on bestbuy|on walmart|on b&h|on bhphoto|on micro center|"
            r"amazon|newegg|best buy|bestbuy|walmart|b&h|bhphoto|micro center|microcenter|right now|today)\b.*$",
            "",
            q,
            flags=re.IGNORECASE,
        ).strip()
        return q.strip(" .,:;\"'")

    # Patterns like: "compare prices for X" / "compare prices on Amazon and Newegg for X"
    m = re.search(r"\bcompare\b.*\bprices?\b\s+(?:for|on)\s+(.+)", lowered, flags=re.IGNORECASE)
    if m:
        q = raw[m.start(1) :].strip()
        q = re.sub(
            r"\b(on amazon|on newegg|on best buy|on bestbuy|on walmart|on b&h|on bhphoto|on micro center|"
            r"amazon|newegg|best buy|bestbuy|walmart|b&h|bhphoto|micro center|microcenter|right now|today)\b.*$",
            "",
            q,
            flags=re.IGNORECASE,
        ).strip()
        return q.strip(" .,:;\"'")

    # Fallback: strip common instruction phrases.
    q = raw
    q = re.sub(r"\b(find|compare|search)\b", "", q, flags=re.IGNORECASE)
    q = re.sub(r"\b(best price|deal finder|prices)\b", "", q, flags=re.IGNORECASE)
    q = re.sub(
        r"\b(amazon|newegg|best buy|bestbuy|walmart|b&h|bhphoto|micro center|microcenter|"
        r"or any other legit sites|right now|today)\b",
        "",
        q,
        flags=re.IGNORECASE,
    )
    q = re.sub(r"\s+", " ", q).strip()
    return q.strip(" .,:;\"'")


def _try_fetch_html_playwright(
    url: str,
    *,
    profile_name: Optional[str] = None,
    headless: bool = True,
) -> Tuple[str, str]:
    """Fetch HTML via Playwright (best-effort).

    This is intentionally optional and only used as a fallback when Requests is blocked.
    """
    try:
        from chintu_backend.automation.browser.browser_controller import get_browser_controller
    except Exception:
        return "", "Playwright browser controller not available."

    try:
        controller = get_browser_controller(headless=headless, profile_name=profile_name)
        controller.open_url(url, wait_for="domcontentloaded")
        html = ""
        try:
            html = controller.get_page_html(max_chars=450_000)
        except Exception as exc:  # noqa: BLE001
            return "", f"Playwright HTML read failed: {exc}"
        if not html:
            return "", "Playwright returned empty HTML."
        return html, ""
    except Exception as exc:  # noqa: BLE001
        return "", f"Playwright fetch failed: {exc}"


def _try_fetch_html_playwright_dual(
    url: str,
    *,
    profile_name: Optional[str] = None,
) -> Tuple[str, str]:
    """Try Playwright in headless mode first, then headed mode for anti-bot pages."""
    html, err = _try_fetch_html_playwright(url, profile_name=profile_name, headless=True)
    if html:
        return html, ""
    html2, err2 = _try_fetch_html_playwright(url, profile_name=profile_name, headless=False)
    if html2:
        return html2, ""
    merged = "; ".join(part for part in [err, err2] if str(part).strip())
    return "", (merged or "Playwright fallback failed.")


def _is_amazon_sponsored(block) -> bool:
    """Best-effort: detect Amazon 'Sponsored' listings inside a result block."""
    try:
        # Some result headers carry an aria-label that explicitly marks sponsorship.
        h2 = block.select_one("h2")
        if h2:
            aria = str(h2.get("aria-label") or "").strip().lower()
            if "sponsored" in aria:
                return True

        # Common explicit label patterns.
        selectors = [
            "span.puis-sponsored-label-text",
            "span.sponsored-label-text",
            "span[data-component-type*='s-sponsored']",
            "span[data-testid*='sponsored']",
        ]
        for sel in selectors:
            if block.select_one(sel):
                return True

        # Fallback: look for exact label text in nearby spans.
        for el in block.select("span"):
            txt = (el.get_text(" ", strip=True) or "").strip().lower()
            if txt in {"sponsored", "sponsored ad", "sponsored.", "ad"}:
                return True
    except Exception:
        return False
    return False


def _extract_amazon_title(block) -> str:
    try:
        h2 = block.select_one("h2")
        title_el = (h2.select_one("span") if h2 else None) or h2
        title = title_el.get_text(" ", strip=True) if title_el else ""
        return str(title or "").strip()
    except Exception:
        return ""


def _extract_amazon_price(block) -> Optional[float]:
    # Most reliable pattern (when present).
    try:
        offscreen = block.select_one("span.a-price span.a-offscreen")
        if offscreen:
            price = _parse_money(offscreen.get_text(strip=True))
            if price is not None:
                return price
    except Exception:
        pass

    # Fallback: whole + fraction.
    try:
        whole = block.select_one("span.a-price-whole")
        frac = block.select_one("span.a-price-fraction")
        if whole:
            whole_txt = (whole.get_text(strip=True) or "").strip().replace(",", "")
            frac_txt = (frac.get_text(strip=True) if frac else "00") or "00"
            raw = f"{whole_txt}.{frac_txt}"
            price = _parse_money(raw)
            if price is not None:
                return price
    except Exception:
        pass

    return None


def _parse_amazon_search_html(
    html: str,
    *,
    source_url: str,
    status_code: int,
    max_results: int,
) -> List[DealListing]:
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    blocks = soup.select('div[data-component-type="s-search-result"]')
    listings: List[DealListing] = []

    for block in blocks:
        asin = (block.get("data-asin") or "").strip()
        if not asin:
            continue

        if _is_amazon_sponsored(block):
            continue

        title = _extract_amazon_title(block)
        price = _extract_amazon_price(block)
        if price is None:
            continue

        item_url = f"https://www.amazon.com/dp/{asin}"
        listings.append(
            DealListing(
                vendor="amazon",
                title=title or f"ASIN {asin}",
                price=price,
                shipping=None,
                url=item_url,
                meta={
                    "asin": asin,
                    "source_url": source_url,
                    "status_code": int(status_code),
                },
            )
        )
        if len(listings) >= max(1, int(max_results)):
            break

    return listings


def fetch_amazon_listings(
    query: str,
    *,
    max_results: int = 6,
    enable_playwright_fallback: bool = True,
    playwright_profile: Optional[str] = "shopping",
) -> Tuple[List[DealListing], str]:
    """Extract listings from Amazon search results (best-effort, read-only)."""
    url = f"https://www.amazon.com/s?k={quote_plus(query)}"
    resp, req_err = _fetch_with_requests_retries(url, timeout_s=20, max_attempts=3)
    if resp is None:
        if not enable_playwright_fallback:
            return [], f"Amazon request failed: {req_err}"
        html_fb, err_fb = _try_fetch_html_playwright_dual(url, profile_name=playwright_profile)
        if html_fb and not _looks_blocked_amazon(html_fb):
            listings = _parse_amazon_search_html(
                html_fb,
                source_url=url,
                status_code=200,
                max_results=max_results,
            )
            for it in listings:
                try:
                    it.meta["source"] = "playwright"
                except Exception:
                    pass
            if listings:
                return listings, ""
        return [], f"Amazon request failed: {req_err}. Playwright fallback error: {err_fb}".strip()

    html = resp.text or ""
    if resp.status_code >= 400:
        if enable_playwright_fallback and _status_retryable(int(resp.status_code)):
            html_fb, err_fb = _try_fetch_html_playwright_dual(url, profile_name=playwright_profile)
            if html_fb and not _looks_blocked_amazon(html_fb):
                listings = _parse_amazon_search_html(
                    html_fb,
                    source_url=url,
                    status_code=200,
                    max_results=max_results,
                )
                for it in listings:
                    try:
                        it.meta["source"] = "playwright"
                    except Exception:
                        pass
                if listings:
                    return listings, ""
            return [], f"Amazon returned HTTP {resp.status_code}. Playwright fallback error: {err_fb}".strip()
        return [], f"Amazon returned HTTP {resp.status_code}"

    if _looks_blocked_amazon(html) and enable_playwright_fallback:
        html2, err2 = _try_fetch_html_playwright_dual(url, profile_name=playwright_profile)
        if html2 and not _looks_blocked_amazon(html2):
            listings = _parse_amazon_search_html(
                html2,
                source_url=url,
                status_code=200,
                max_results=max_results,
            )
            # Tag source for auditability.
            for it in listings:
                try:
                    it.meta["source"] = "playwright"
                except Exception:
                    pass
            if listings:
                return listings, ""
        if err2:
            return [], f"Amazon blocked Requests (captcha/robot check). Playwright fallback error: {err2}"
        return [], "Amazon blocked the request (captcha/robot check)."

    if _looks_blocked_amazon(html):
        return [], "Amazon blocked the request (captcha/robot check)."

    listings = _parse_amazon_search_html(
        html,
        source_url=url,
        status_code=int(resp.status_code),
        max_results=max_results,
    )
    for it in listings:
        try:
            it.meta["source"] = "requests"
        except Exception:
            pass
    return listings, ""


def _extract_newegg_initial_state(html: str) -> Tuple[Optional[Dict[str, Any]], str]:
    marker = "window.__initialState__ = "
    start = html.find(marker)
    if start < 0:
        return None, "Newegg initial state not found in page."
    start += len(marker)
    s = html[start:]
    if not s:
        return None, "Newegg initial state was empty."
    # The JSON object begins with '{' and ends at the matching closing brace.
    i0 = s.find("{")
    if i0 < 0:
        return None, "Newegg initial state JSON start not found."
    s = s[i0:]
    level = 0
    end = None
    for i, ch in enumerate(s):
        if ch == "{":
            level += 1
        elif ch == "}":
            level -= 1
            if level == 0:
                end = i + 1
                break
    if end is None:
        return None, "Newegg initial state JSON end not found."
    js = s[:end]
    try:
        return json.loads(js), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"Newegg state JSON parse failed: {exc}"


def _extract_newegg_next_data(html: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Fallback: parse __NEXT_DATA__ payload when initialState is missing."""
    try:
        import json
        import re as _re

        m = _re.search(r"<script[^>]+id=\"__NEXT_DATA__\"[^>]*>(\\{.*?\\})</script>", html, flags=_re.DOTALL)
        if not m:
            return None, "__NEXT_DATA__ not found."
        payload = json.loads(m.group(1))
        if not isinstance(payload, dict):
            return None, "__NEXT_DATA__ was not an object."
        return payload, ""
    except Exception as exc:  # noqa: BLE001
        return None, f"__NEXT_DATA__ parse failed: {exc}"


def _parse_newegg_state_products(
    products: List[Dict[str, Any]],
    *,
    source_url: str,
    status_code: int,
    max_results: int,
) -> List[DealListing]:
    listings: List[DealListing] = []
    for prod in products:
        if not isinstance(prod, dict):
            continue
        ic = prod.get("ItemCell") or {}
        if not isinstance(ic, dict):
            continue
        desc = ic.get("Description") or {}
        if not isinstance(desc, dict):
            desc = {}
        title = str(desc.get("Title") or desc.get("ProductName") or desc.get("WebDescription") or "").strip()

        price = _parse_money(str(ic.get("FinalPrice") or ""))  # already numeric-like
        if price is None:
            continue

        ship = ic.get("ShippingCharge")
        shipping = None
        if ship is not None:
            shipping = _parse_money(str(ship))
            if shipping is not None and shipping < 0.01:
                shipping = 0.0

        product_number = str(prod.get("ProductNumber") or ic.get("Item") or "").strip()
        if not product_number:
            continue
        item_url = f"https://www.newegg.com/p/{product_number}"

        listings.append(
            DealListing(
                vendor="newegg",
                title=title or f"Newegg {product_number}",
                price=price,
                shipping=shipping,
                url=item_url,
                meta={
                    "product_number": product_number,
                    "source_url": source_url,
                    "status_code": int(status_code),
                    "in_stock": bool(ic.get("Instock", True)),
                    "seller": (ic.get("Seller") or {}).get("SellerName") if isinstance(ic.get("Seller"), dict) else None,
                },
            )
        )
        if len(listings) >= max(1, int(max_results)):
            break
    return listings


def fetch_newegg_listings(
    query: str,
    *,
    max_results: int = 6,
    enable_playwright_fallback: bool = True,
    playwright_profile: Optional[str] = "shopping",
) -> Tuple[List[DealListing], str]:
    """Extract listings from Newegg search results (best-effort, read-only)."""
    url = f"https://www.newegg.com/p/pl?d={quote_plus(query)}"
    resp, req_err = _fetch_with_requests_retries(url, timeout_s=20, max_attempts=3)
    if resp is None:
        if not enable_playwright_fallback:
            return [], f"Newegg request failed: {req_err}"
        html_fb, err_fb = _try_fetch_html_playwright_dual(url, profile_name=playwright_profile)
        if html_fb and not _looks_blocked_newegg(html_fb):
            state, err = _extract_newegg_initial_state(html_fb)
            if not err and isinstance(state, dict):
                products = state.get("Products")
                if isinstance(products, list) and products:
                    listings = _parse_newegg_state_products(
                        products,
                        source_url=url,
                        status_code=200,
                        max_results=max_results,
                    )
                    for it in listings:
                        try:
                            it.meta["source"] = "playwright"
                        except Exception:
                            pass
                    if listings:
                        return listings, ""
        return [], f"Newegg request failed: {req_err}. Playwright fallback error: {err_fb}".strip()

    html = resp.text or ""
    if resp.status_code >= 400:
        if enable_playwright_fallback and _status_retryable(int(resp.status_code)):
            html_fb, err_fb = _try_fetch_html_playwright_dual(url, profile_name=playwright_profile)
            if html_fb and not _looks_blocked_newegg(html_fb):
                state, err = _extract_newegg_initial_state(html_fb)
                if not err and isinstance(state, dict):
                    products = state.get("Products")
                    if isinstance(products, list) and products:
                        listings = _parse_newegg_state_products(
                            products,
                            source_url=url,
                            status_code=200,
                            max_results=max_results,
                        )
                        for it in listings:
                            try:
                                it.meta["source"] = "playwright"
                            except Exception:
                                pass
                        if listings:
                            return listings, ""
            return [], f"Newegg returned HTTP {resp.status_code}. Playwright fallback error: {err_fb}".strip()
        return [], f"Newegg returned HTTP {resp.status_code}"

    if _looks_blocked_newegg(html) and enable_playwright_fallback:
        html2, err2 = _try_fetch_html_playwright_dual(url, profile_name=playwright_profile)
        if html2 and not _looks_blocked_newegg(html2):
            state, err = _extract_newegg_initial_state(html2)
            if not err and isinstance(state, dict):
                products = state.get("Products")
                if isinstance(products, list) and products:
                    listings = _parse_newegg_state_products(
                        products,
                        source_url=url,
                        status_code=200,
                        max_results=max_results,
                    )
                    for it in listings:
                        try:
                            it.meta["source"] = "playwright"
                        except Exception:
                            pass
                    if listings:
                        return listings, ""
            if err2:
                return [], f"Newegg blocked Requests (captcha/access denied). Playwright fallback error: {err2}"
        if err2:
            return [], f"Newegg blocked the request (captcha/access denied). Playwright fallback error: {err2}"
        return [], "Newegg blocked the request (captcha/access denied)."

    if _looks_blocked_newegg(html):
        return [], "Newegg blocked the request (captcha/access denied)."

    state, err = _extract_newegg_initial_state(html)
    if err or not isinstance(state, dict):
        # Fallback: try __NEXT_DATA__ for newer site variants.
        next_data, next_err = _extract_newegg_next_data(html)
        if next_err:
            return [], err or next_err
        # Best-effort: some Newegg pages include products under props/pageProps/initialState too.
        try:
            candidate = (
                (((next_data or {}).get("props") or {}).get("pageProps") or {}).get("initialState")
                if isinstance(next_data, dict)
                else None
            )
            if isinstance(candidate, dict):
                state = candidate
            else:
                return [], "Newegg initial state not found in page."
        except Exception:
            return [], "Newegg initial state not found in page."
    if not isinstance(state, dict):
        return [], "Newegg state payload was not a JSON object."

    products = state.get("Products")
    if not isinstance(products, list) or not products:
        return [], "Newegg returned no products."

    listings = _parse_newegg_state_products(
        products,
        source_url=url,
        status_code=int(resp.status_code),
        max_results=max_results,
    )
    for it in listings:
        try:
            it.meta["source"] = "requests"
        except Exception:
            pass
    return listings, ""


def _looks_blocked_bestbuy(html: str) -> bool:
    low = (html or "").lower()
    return _looks_blocked_generic(low) or any(
        s in low
        for s in [
            "automated access to our site",
            "please verify you are a human",
            "access denied",
            "captcha",
        ]
    )


def fetch_bestbuy_listings(
    query: str,
    *,
    max_results: int = 6,
    enable_playwright_fallback: bool = True,
    playwright_profile: Optional[str] = "shopping",
) -> Tuple[List[DealListing], str]:
    """Extract listings from BestBuy search results (best-effort, read-only)."""
    url = f"https://www.bestbuy.com/site/searchpage.jsp?st={quote_plus(query)}"

    html, status, err = _fetch_html_requests(url, timeout_s=20)
    if err:
        return [], f"BestBuy request failed: {err}"
    if status >= 400:
        return [], f"BestBuy returned HTTP {status}"

    if _looks_blocked_bestbuy(html) and enable_playwright_fallback:
        html2, err2 = _try_fetch_html_playwright(url, profile_name=playwright_profile, headless=True)
        if html2 and not _looks_blocked_bestbuy(html2):
            html = html2
            status = 200
        else:
            return [], f"BestBuy blocked the request (captcha/access denied). {err2}".strip()

    if _looks_blocked_bestbuy(html):
        return [], "BestBuy blocked the request (captcha/access denied)."

    try:
        from bs4 import BeautifulSoup
    except Exception as exc:  # noqa: BLE001
        return [], f"Missing dependencies for BestBuy parsing: {exc}"

    soup = BeautifulSoup(html or "", "html.parser")
    blocks = soup.select("li.sku-item")
    listings: List[DealListing] = []

    for block in blocks:
        # Skip sponsored-ish items when detectable.
        try:
            head_txt = (block.get_text(" ", strip=True) or "")[:200].lower()
            if "sponsored" in head_txt:
                continue
        except Exception:
            pass

        title_a = block.select_one("h4.sku-title a")
        title = (title_a.get_text(" ", strip=True) if title_a else "") or ""
        href = (title_a.get("href") if title_a else "") or ""
        if href and href.startswith("/"):
            href = "https://www.bestbuy.com" + href

        price_el = (
            block.select_one("div.priceView-customer-price span[aria-hidden='true']")
            or block.select_one("div.priceView-customer-price span")
        )
        price = _parse_money(price_el.get_text(" ", strip=True) if price_el else "")

        if not title or not href or price is None:
            continue

        listings.append(
            DealListing(
                vendor="bestbuy",
                title=title.strip(),
                price=price,
                shipping=None,
                url=href,
                meta={"source_url": url, "status_code": int(status), "source": "requests"},
            )
        )
        if len(listings) >= max(1, int(max_results)):
            break

    # JSON-LD fallback (some variants render fewer visible nodes).
    if not listings:
        for name, price, href in _extract_products_from_jsonld(html, base_url="https://www.bestbuy.com", max_results=max_results):
            if price is None:
                continue
            listings.append(
                DealListing(
                    vendor="bestbuy",
                    title=name.strip(),
                    price=price,
                    shipping=None,
                    url=href,
                    meta={"source_url": url, "status_code": int(status), "source": "jsonld"},
                )
            )
            if len(listings) >= max(1, int(max_results)):
                break

    return listings, ""


def fetch_bhphoto_listings(
    query: str,
    *,
    max_results: int = 6,
    enable_playwright_fallback: bool = True,
    playwright_profile: Optional[str] = "shopping",
) -> Tuple[List[DealListing], str]:
    """Extract listings from B&H search results (best-effort, read-only)."""
    base = "https://www.bhphotovideo.com"
    url = f"{base}/c/search?Ntt={quote_plus(query)}&N=0&InitialSearch=yes&sts=ma"

    html, status, err = _fetch_html_requests(url, timeout_s=20)
    if err:
        return [], f"B&H request failed: {err}"
    if status >= 400:
        return [], f"B&H returned HTTP {status}"

    if _looks_blocked_generic(html) and enable_playwright_fallback:
        html2, err2 = _try_fetch_html_playwright(url, profile_name=playwright_profile, headless=True)
        if html2 and not _looks_blocked_generic(html2):
            html = html2
            status = 200
        else:
            return [], f"B&H blocked the request. {err2}".strip()

    if _looks_blocked_generic(html):
        return [], "B&H blocked the request (captcha/access denied)."

    try:
        from bs4 import BeautifulSoup
    except Exception as exc:  # noqa: BLE001
        return [], f"Missing dependencies for B&H parsing: {exc}"

    soup = BeautifulSoup(html or "", "html.parser")
    blocks = soup.select("[data-selenium='itemTile'], [data-selenium='miniProductPage']")
    if not blocks:
        blocks = soup.select("div[data-selenium*='item']")

    listings: List[DealListing] = []

    for block in blocks:
        title_a = (
            block.select_one("[data-selenium='itemTitle'] a")
            or block.select_one("a[data-selenium='itemTitle']")
            or block.select_one("h3 a")
            or block.select_one("h2 a")
        )
        title = (title_a.get_text(" ", strip=True) if title_a else "") or ""
        href = (title_a.get("href") if title_a else "") or ""
        if href.startswith("/"):
            href = base + href

        price_el = (
            block.select_one("[data-selenium='pricingPrice']")
            or block.select_one("[data-selenium='itemPrice']")
            or block.select_one("span[class*='Price']")
            or block.select_one("div[class*='Price']")
        )
        price = _parse_money(price_el.get_text(" ", strip=True) if price_el else "")

        if not title or not href or price is None:
            continue

        listings.append(
            DealListing(
                vendor="bhphoto",
                title=title.strip(),
                price=price,
                shipping=None,
                url=href,
                meta={"source_url": url, "status_code": int(status), "source": "requests"},
            )
        )
        if len(listings) >= max(1, int(max_results)):
            break

    if not listings:
        for name, price, href in _extract_products_from_jsonld(html, base_url=base, max_results=max_results):
            if price is None or not href:
                continue
            listings.append(
                DealListing(
                    vendor="bhphoto",
                    title=name.strip(),
                    price=price,
                    shipping=None,
                    url=href,
                    meta={"source_url": url, "status_code": int(status), "source": "jsonld"},
                )
            )
            if len(listings) >= max(1, int(max_results)):
                break

    return listings, ""


def fetch_microcenter_listings(
    query: str,
    *,
    max_results: int = 6,
    enable_playwright_fallback: bool = True,
    playwright_profile: Optional[str] = "shopping",
) -> Tuple[List[DealListing], str]:
    """Extract listings from Micro Center search results (best-effort, read-only)."""
    base = "https://www.microcenter.com"
    url = f"{base}/search/search_results.aspx?Ntt={quote_plus(query)}"

    html, status, err = _fetch_html_requests(url, timeout_s=20)
    if err:
        return [], f"Micro Center request failed: {err}"
    if status >= 400:
        return [], f"Micro Center returned HTTP {status}"

    if _looks_blocked_generic(html) and enable_playwright_fallback:
        html2, err2 = _try_fetch_html_playwright(url, profile_name=playwright_profile, headless=True)
        if html2 and not _looks_blocked_generic(html2):
            html = html2
            status = 200
        else:
            return [], f"Micro Center blocked the request. {err2}".strip()

    if _looks_blocked_generic(html):
        return [], "Micro Center blocked the request (captcha/access denied)."

    try:
        from bs4 import BeautifulSoup
    except Exception as exc:  # noqa: BLE001
        return [], f"Missing dependencies for Micro Center parsing: {exc}"

    soup = BeautifulSoup(html or "", "html.parser")
    blocks = soup.select("div.product_wrapper, li.product_wrapper")
    listings: List[DealListing] = []

    for block in blocks:
        title_a = block.select_one("h2 a") or block.select_one("a[data-name]")
        title = (title_a.get_text(" ", strip=True) if title_a else "") or ""
        href = (title_a.get("href") if title_a else "") or ""
        if href.startswith("/"):
            href = base + href

        price_el = (
            block.select_one("span[itemprop='price']")
            or block.select_one("span.price")
            or block.select_one("div.price")
            or block.select_one("span[class*='price']")
        )
        price = _parse_money(price_el.get_text(" ", strip=True) if price_el else "")

        if not title or not href or price is None:
            continue

        listings.append(
            DealListing(
                vendor="microcenter",
                title=title.strip(),
                price=price,
                shipping=None,
                url=href,
                meta={"source_url": url, "status_code": int(status), "source": "requests"},
            )
        )
        if len(listings) >= max(1, int(max_results)):
            break

    if not listings:
        for name, price, href in _extract_products_from_jsonld(html, base_url=base, max_results=max_results):
            if price is None or not href:
                continue
            listings.append(
                DealListing(
                    vendor="microcenter",
                    title=name.strip(),
                    price=price,
                    shipping=None,
                    url=href,
                    meta={"source_url": url, "status_code": int(status), "source": "jsonld"},
                )
            )
            if len(listings) >= max(1, int(max_results)):
                break

    return listings, ""


def _extract_walmart_next_data(html: str) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', html or "", flags=re.DOTALL)
        if not m:
            return None, "__NEXT_DATA__ not found."
        data = json.loads(m.group(1))
        return (data if isinstance(data, dict) else None), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"__NEXT_DATA__ parse failed: {exc}"


def fetch_walmart_listings(
    query: str,
    *,
    max_results: int = 6,
    enable_playwright_fallback: bool = True,
    playwright_profile: Optional[str] = "shopping",
) -> Tuple[List[DealListing], str]:
    """Extract listings from Walmart search results (best-effort, read-only)."""
    base = "https://www.walmart.com"
    url = f"{base}/search?q={quote_plus(query)}"

    html, status, err = _fetch_html_requests(url, timeout_s=20)
    if err:
        return [], f"Walmart request failed: {err}"
    if status >= 400:
        return [], f"Walmart returned HTTP {status}"

    if _looks_blocked_generic(html) and enable_playwright_fallback:
        html2, err2 = _try_fetch_html_playwright(url, profile_name=playwright_profile, headless=True)
        if html2 and not _looks_blocked_generic(html2):
            html = html2
            status = 200
        else:
            return [], f"Walmart blocked the request. {err2}".strip()

    if _looks_blocked_generic(html):
        return [], "Walmart blocked the request (captcha/access denied)."

    listings: List[DealListing] = []

    # 1) JSON-LD fast-path (works well on product pages and some search pages).
    for name, price, href in _extract_products_from_jsonld(html, base_url=base, max_results=max_results * 2):
        if price is None or not href:
            continue
        listings.append(
            DealListing(
                vendor="walmart",
                title=name.strip(),
                price=price,
                shipping=None,
                url=href,
                meta={"source_url": url, "status_code": int(status), "source": "jsonld"},
            )
        )
        if len(listings) >= max(1, int(max_results)):
            return listings, ""

    # 2) __NEXT_DATA__ fallback (best-effort; schema may change).
    payload, nerr = _extract_walmart_next_data(html)
    if nerr or not isinstance(payload, dict):
        return listings, "" if listings else (nerr or "Walmart data not found.")

    def _walk(obj: Any) -> None:
        if len(listings) >= max(1, int(max_results)):
            return
        if isinstance(obj, dict):
            # Candidate shape found in some Walmart variants.
            name = obj.get("name")
            canonical = obj.get("canonicalUrl") or obj.get("productUrl") or obj.get("url")
            price = None
            if isinstance(obj.get("price"), (int, float, str)):
                price = _parse_money(str(obj.get("price")))
            price_info = obj.get("priceInfo")
            if price is None and isinstance(price_info, dict):
                cur = price_info.get("currentPrice")
                if isinstance(cur, dict):
                    price = _parse_money(str(cur.get("price") or ""))
            if name and canonical and price is not None:
                href = str(canonical)
                if href.startswith("/"):
                    href = base + href
                listings.append(
                    DealListing(
                        vendor="walmart",
                        title=str(name).strip(),
                        price=price,
                        shipping=None,
                        url=href,
                        meta={"source_url": url, "status_code": int(status), "source": "next_data"},
                    )
                )
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for it in obj:
                _walk(it)

    _walk(payload)
    return listings, ""


def _ddg_text_results(query: str, *, max_results: int = 10, region: str = "us-en") -> List[Dict[str, str]]:
    """DuckDuckGo text results using ddgs (best-effort)."""
    q = str(query or "").strip()
    if not q:
        return []

    DDGS = None
    try:
        from ddgs import DDGS as _DDGS

        DDGS = _DDGS
    except Exception:
        try:
            from duckduckgo_search import DDGS as _DDGS

            DDGS = _DDGS
        except Exception:
            DDGS = None

    if DDGS is None:
        return []

    try:
        with DDGS() as ddgs:
            return list(ddgs.text(q, max_results=min(int(max_results), 25), region=region))
    except Exception:
        return []


def fetch_web_listings(
    query: str,
    *,
    max_results: int = 8,
    allowed_domains: Optional[List[str]] = None,
) -> Tuple[List[DealListing], str]:
    """Search the web for trusted retailer product pages and parse JSON-LD prices."""
    allowed = allowed_domains or list(_TRUSTED_WEB_DOMAINS)
    q = str(query or "").strip()
    if not q:
        return [], "Missing query."

    results = _ddg_text_results(f"{q} price", max_results=max_results * 2)
    if not results:
        return [], "Web search unavailable or returned no results."

    listings: List[DealListing] = []
    seen: set[str] = set()

    for res in results:
        href = str((res or {}).get("href") or "").strip()
        if not href or href in seen:
            continue
        seen.add(href)

        domain = _normalize_domain(href)
        if not _domain_allowed(domain, allowed):
            continue

        html, status, err = _fetch_html_requests(href, timeout_s=20)
        if err or status >= 400 or _looks_blocked_generic(html):
            continue

        base = f"https://{domain}" if domain else ""
        products = _extract_products_from_jsonld(html, base_url=base, max_results=3)
        picked = next(((n, p, u) for (n, p, u) in products if p is not None and u), None)
        if not picked:
            continue
        name, price, url = picked
        if price is None:
            continue

        listings.append(
            DealListing(
                vendor=f"web:{domain}",
                title=str(name).strip() or domain,
                price=float(price),
                shipping=None,
                url=str(url),
                meta={
                    "source": "ddg+jsonld",
                    "domain": domain,
                    "source_url": href,
                    "status_code": int(status),
                },
            )
        )
        if len(listings) >= max(1, int(max_results)):
            break

    return listings, ""


def _default_vendors() -> List[str]:
    # Keep a reliable baseline; "web" is opt-in via include_web_search.
    return ["amazon", "newegg", "bestbuy", "bhphoto", "microcenter", "walmart"]


def _vendor_search_link(vendor: str, query: str) -> str:
    q = quote_plus(query)
    if vendor == "amazon":
        return f"https://www.amazon.com/s?k={q}"
    if vendor == "newegg":
        return f"https://www.newegg.com/p/pl?d={q}"
    if vendor == "bestbuy":
        return f"https://www.bestbuy.com/site/searchpage.jsp?st={q}"
    if vendor == "bhphoto":
        return f"https://www.bhphotovideo.com/c/search?Ntt={q}&N=0&InitialSearch=yes&sts=ma"
    if vendor == "microcenter":
        return f"https://www.microcenter.com/search/search_results.aspx?Ntt={q}"
    if vendor == "walmart":
        return f"https://www.walmart.com/search?q={q}"
    return ""


def run_deal_finder(
    query: str,
    *,
    vendors: Optional[List[str]] = None,
    max_results_per_vendor: int = 6,
    include_web_search: bool = False,
    max_web_results: int = 8,
    enable_playwright_fallback: bool = True,
) -> Tuple[List[str], Dict[str, List[DealListing]], Dict[str, str], List[DealListing]]:
    query = str(query or "").strip()
    requested = [str(v).strip().lower() for v in (vendors or []) if str(v).strip()]
    supported = {"amazon", "newegg", "bestbuy", "bhphoto", "microcenter", "walmart", "web"}

    vendors_final: List[str] = []
    for v in requested:
        if v in supported and v not in vendors_final:
            vendors_final.append(v)
    if not vendors_final:
        vendors_final = _default_vendors()
    if include_web_search and "web" not in vendors_final:
        vendors_final.append("web")

    max_results = max(1, min(int(max_results_per_vendor or 6), 20))
    web_results = max(1, min(int(max_web_results or 8), 25))

    per_vendor: Dict[str, List[DealListing]] = {}
    errors: Dict[str, str] = {}

    fetchers = {
        "amazon": lambda: fetch_amazon_listings(
            query,
            max_results=max_results,
            enable_playwright_fallback=enable_playwright_fallback,
        ),
        "newegg": lambda: fetch_newegg_listings(
            query,
            max_results=max_results,
            enable_playwright_fallback=enable_playwright_fallback,
        ),
        "bestbuy": lambda: fetch_bestbuy_listings(
            query,
            max_results=max_results,
            enable_playwright_fallback=enable_playwright_fallback,
        ),
        "bhphoto": lambda: fetch_bhphoto_listings(
            query,
            max_results=max_results,
            enable_playwright_fallback=enable_playwright_fallback,
        ),
        "microcenter": lambda: fetch_microcenter_listings(
            query,
            max_results=max_results,
            enable_playwright_fallback=enable_playwright_fallback,
        ),
        "walmart": lambda: fetch_walmart_listings(
            query,
            max_results=max_results,
            enable_playwright_fallback=enable_playwright_fallback,
        ),
        "web": lambda: fetch_web_listings(
            query,
            max_results=web_results,
            allowed_domains=list(_TRUSTED_WEB_DOMAINS),
        ),
    }

    for vendor in vendors_final:
        fetch = fetchers.get(vendor)
        if fetch is None:
            continue
        items, err = fetch()
        per_vendor[vendor] = items
        if err:
            errors[vendor] = err

    combined: List[DealListing] = []
    for vendor in vendors_final:
        combined.extend(per_vendor.get(vendor, []))
    combined = [item for item in combined if item.total is not None]
    combined.sort(key=lambda x: float(x.total or 1e18))

    return vendors_final, per_vendor, errors, combined


def _split_comparison_products(query: str) -> List[str]:
    raw = str(query or "").strip()
    if not raw:
        return []
    lowered = raw.lower()
    has_compare_signal = (
        " vs " in lowered
        or " versus " in lowered
        or lowered.startswith("compare ")
        or "compare " in lowered
        or "which is better" in lowered
    )
    if not has_compare_signal:
        return []

    cleaned = re.sub(r"^\s*(compare|comparison of|which is better:?)\s+", "", raw, flags=re.IGNORECASE).strip()
    parts = re.split(r"\bvs\.?\b|\bversus\b|,|/|\band\b", cleaned, flags=re.IGNORECASE)

    products: List[str] = []
    for part in parts:
        p = str(part or "").strip(" .,:;\"'")
        p = re.sub(r"\b(which is better|best|price|prices|compare|for|between)\b", "", p, flags=re.IGNORECASE).strip()
        p = re.sub(r"\s+", " ", p).strip()
        if len(p) < 2:
            continue
        if p.lower() in {"the", "and", "or"}:
            continue
        if p not in products:
            products.append(p)

    if len(products) < 2:
        return []
    return products[:5]


def _looks_non_shopping_query(raw_text: str, query: str, products: List[str]) -> bool:
    """Heuristic: route abstract comparisons back to conversation, not deal-finder."""
    text = str(raw_text or "").lower()
    q = str(query or "").lower()
    joined = f"{text} {q}"

    shopping_intents = [
        "price",
        "prices",
        "deal",
        "buy",
        "purchase",
        "cost",
        "cheapest",
        "amazon",
        "newegg",
        "bestbuy",
        "walmart",
        "bhphoto",
        "microcenter",
    ]
    if any(k in joined for k in shopping_intents):
        return False

    software_terms = {
        "python",
        "javascript",
        "typescript",
        "java",
        "c++",
        "rust",
        "golang",
        "go language",
        "react",
        "vue",
        "angular",
        "django",
        "flask",
        "fastapi",
        "node",
        "nodejs",
        "sql",
        "postgres",
        "mongodb",
        "linux",
        "windows",
        "macos",
    }

    candidates = products or _split_comparison_products(query)
    if not candidates:
        return False
    matched = 0
    for item in candidates:
        low = str(item or "").strip().lower()
        if any(term == low or term in low for term in software_terms):
            matched += 1
    return matched >= max(2, len(candidates))


def _render_comparison_table(rows: List[Dict[str, Any]]) -> str:
    lines = [
        "| Product | Best Total | Vendor | Listings | Link |",
        "| :-- | --: | :-- | --: | :-- |",
    ]
    for row in rows:
        product = str(row.get("product") or "").replace("|", " ").strip()
        total = row.get("best_total")
        total_text = f"${float(total):,.2f}" if isinstance(total, (int, float)) else "n/a"
        vendor = str(row.get("best_vendor") or "n/a")
        count = int(row.get("listing_count") or 0)
        url = str(row.get("best_url") or "")
        lines.append(f"| {product} | {total_text} | {vendor} | {count} | {url} |")
    return "\n".join(lines)


def _render_table(listings: List[DealListing]) -> str:
    def money(x: Optional[float]) -> str:
        if x is None:
            return ""
        return f"${x:,.2f}"

    lines: List[str] = []
    lines.append("| Vendor | Price | Ship | Total | Item | Link |")
    lines.append("| :-- | --: | --: | --: | :-- | :-- |")
    for it in listings:
        title = (it.title or "").replace("|", " ").strip()
        if len(title) > 70:
            title = title[:67].rstrip() + "..."
        lines.append(
            "| {vendor} | {price} | {ship} | {total} | {title} | {url} |".format(
                vendor=it.vendor,
                price=money(it.price),
                ship=money(it.shipping),
                total=money(it.total),
                title=title,
                url=it.url,
            )
        )
    return "\n".join(lines)


def handle_deal_finder(text: str, context: Dict[str, Any]) -> ActionResult:
    validated = context.get("_validated_params")
    query = ""
    comparison_products: List[str] = []
    vendors = _default_vendors()
    max_results = 6
    include_web_search = False
    max_web_results = 8
    if validated and isinstance(validated, DealFinderSchema):
        query = str(validated.query or "").strip()
        comparison_products = [str(p).strip() for p in (validated.comparison_products or []) if str(p).strip()]
        vendors = [str(v).strip().lower() for v in (validated.vendors or []) if str(v).strip()]
        max_results = int(validated.max_results_per_vendor or max_results)
        include_web_search = bool(validated.include_web_search)
        max_web_results = int(validated.max_web_results or max_web_results)

    if not query:
        query = _extract_query(text)
    query = str(query or "").strip()
    if not query:
        return ActionResult.fail("What item should I price-check? Example: 'Find best price for 2TB NVMe SSD'.", "deal_finder")

    started = datetime.now(timezone.utc)

    # Multi-product comparison mode (e.g., "RTX 4060 vs RX 7600").
    if not comparison_products:
        comparison_products = _split_comparison_products(query)
    if _looks_non_shopping_query(text, query, comparison_products):
        return ActionResult.ok("__LLM_ROUTE__", {"reason": "non_shopping_comparison"}, "conversation")
    if len(comparison_products) >= 2:
        rows: List[Dict[str, Any]] = []
        aggregate_errors: Dict[str, Dict[str, str]] = {}

        for product in comparison_products:
            v_final, _per_vendor, errs, combined = run_deal_finder(
                product,
                vendors=vendors,
                max_results_per_vendor=max_results,
                include_web_search=include_web_search,
                max_web_results=max_web_results,
            )
            if errs:
                aggregate_errors[product] = errs
            best = combined[0] if combined else None
            rows.append(
                {
                    "product": product,
                    "vendors": v_final,
                    "listing_count": len(combined),
                    "best_total": (best.total if best else None),
                    "best_vendor": (best.vendor if best else None),
                    "best_url": (best.url if best else ""),
                    "best": (best.to_dict() if best else None),
                }
            )

        ranked = [r for r in rows if isinstance(r.get("best_total"), (int, float))]
        ranked.sort(key=lambda r: float(r.get("best_total") or 1e18))
        if not ranked:
            msg = (
                f"Product comparison: I couldn't extract priced listings for {', '.join(comparison_products)}. "
                "Try more specific model names."
            )
            return ActionResult.ok(
                msg,
                {
                    "mode": "comparison",
                    "query": query,
                    "products": rows,
                    "errors": aggregate_errors,
                },
                "deal_finder",
            )

        winner = ranked[0]
        table = _render_comparison_table(ranked)
        msg = (
            f"**Product Comparison** (UTC {started.strftime('%Y-%m-%d %H:%M')})\n"
            f"- Compared: {', '.join(comparison_products)}\n"
            f"- Lowest current best-total: {winner['product']} at ${float(winner['best_total']):,.2f} ({winner['best_vendor']})\n\n"
            f"{table}"
        ).strip()
        data = {
            "mode": "comparison",
            "query": query,
            "products": ranked,
            "winner": winner,
            "errors": aggregate_errors,
            "include_web_search": include_web_search,
        }

        run_id = context.get("_run_id") if isinstance(context, dict) else None
        if run_id:
            try:
                from chintu_backend.core.run_manager import get_run_manager

                rm = get_run_manager()
                stamp = started.strftime("%Y%m%d_%H%M%S")
                rm.write_artifact(str(run_id), f"product_compare_{stamp}.json", json.dumps(data, indent=2, ensure_ascii=True))
                rm.write_artifact(str(run_id), f"product_compare_{stamp}.md", msg + "\n")
            except Exception:
                pass
        return ActionResult.ok(msg, data, "deal_finder")

    vendors_final, per_vendor, errors, combined = run_deal_finder(
        query,
        vendors=vendors,
        max_results_per_vendor=max_results,
        include_web_search=include_web_search,
        max_web_results=max_web_results,
    )

    if not combined:
        msg_lines = [f"Deal Finder: I couldn't extract prices for '{query}' right now."]
        if errors:
            msg_lines.append("")
            msg_lines.append("Issues:")
            for k, v in errors.items():
                msg_lines.append(f"- {k}: {v}")
        # Always provide direct search links for manual verification / retry.
        msg_lines.append("")
        msg_lines.append("Direct links (manual check):")
        for vendor in vendors_final:
            if vendor == "web":
                continue
            link = _vendor_search_link(vendor, query)
            if link:
                msg_lines.append(f"- {vendor}: {link}")
        if "web" in vendors_final:
            msg_lines.append("- trusted web scan: enabled (allowlist only)")
        msg_lines.append("")
        msg_lines.append("Tip: try a more specific query (brand/model), or re-run in a few minutes.")
        data = {
            "query": query,
            "vendors": vendors_final,
            "errors": errors,
            "results": {},
            "include_web_search": include_web_search,
        }
        return ActionResult.ok("\n".join(msg_lines).strip(), data, "deal_finder")

    best = combined[0]
    table = _render_table(combined[: min(12, len(combined))])
    scanned = ", ".join(vendors_final)

    msg = (
        f"**Deal Finder** (UTC {started.strftime('%Y-%m-%d %H:%M')})\n"
        f"- Query: {query}\n"
        f"- Scanned: {scanned}\n"
        f"- Best (by total): {best.vendor} {best.total:,.2f} -> {best.url}\n\n"
        f"{table}"
    ).strip()

    data = {
        "query": query,
        "vendors": vendors_final,
        "errors": errors,
        "include_web_search": include_web_search,
        "per_vendor_count": {k: len(v or []) for k, v in per_vendor.items()},
        "best": best.to_dict(),
        "listings": [x.to_dict() for x in combined[:50]],
    }

    # Evidence artifacts (best-effort).
    run_id = context.get("_run_id") if isinstance(context, dict) else None
    if run_id:
        try:
            from chintu_backend.core.run_manager import get_run_manager

            rm = get_run_manager()
            stamp = started.strftime("%Y%m%d_%H%M%S")
            rm.write_artifact(str(run_id), f"deal_finder_{stamp}.json", json.dumps(data, indent=2, ensure_ascii=True))
            rm.write_artifact(str(run_id), f"deal_finder_{stamp}.md", msg + "\n")
        except Exception:
            pass

    return ActionResult.ok(msg, data, "deal_finder")


def register_deal_finder_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="deal_finder",
            triggers=[
                "find the best price for",
                "best price for",
                "best price on amazon and newegg",
                "compare amazon vs newegg",
                "compare amazon and newegg",
                "compare prices on amazon and newegg",
                "compare prices amazon vs newegg",
                r"\bcompare\b.*\bvs\b",
                r"\bcompare\b.*\bversus\b",
                "which is better",
                "find the best price on amazon",
                "find the best price on newegg",
                "find best deal",
                "best deal from legit websites",
                "compare prices across websites",
                "find the best price",
                "deal finder",
            ],
            handler=handle_deal_finder,
            requires_confirmation=False,
            description="compare prices across trusted retailers (read-only) and return ranked results + links",
            capability_type=CapabilityType.AI_AGENT,
            examples=[
                "I need a new 2TB NVMe SSD. Find the best price on Amazon and Newegg right now.",
                "Find best deal for iPhone 15 from legit websites.",
                "Deal finder: 2TB NVMe SSD",
            ],
            schema=DealFinderSchema,
        )
    )
