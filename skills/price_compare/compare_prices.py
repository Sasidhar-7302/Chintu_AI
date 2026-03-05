from __future__ import annotations

import re
import sys
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.automation.deal_finder_capabilities import run_deal_finder


REQUEST_TIMEOUT = 12
DEFAULT_OUTPUT = "price_compare.md"
DEFAULT_VENDORS = ["amazon", "newegg", "bestbuy", "walmart", "bhphoto", "microcenter"]
CACHE_MAX_AGE_HOURS = 24 * 14

VENDOR_ALIASES: Dict[str, List[str]] = {
    "amazon": ["amazon", "amzn"],
    "newegg": ["newegg"],
    "bestbuy": ["best buy", "bestbuy"],
    "walmart": ["walmart"],
    "bhphoto": ["b&h", "bh photo", "bhphoto", "bhphotovideo"],
    "microcenter": ["micro center", "microcenter"],
}

BROAD_SITE_SIGNALS = [
    "other sites",
    "other websites",
    "all sites",
    "all websites",
    "legit websites",
    "trusted websites",
    "across websites",
    "across sites",
    "online stores",
]

WEB_EXPANSION_SIGNALS = [
    "include web search",
    "trusted web expansion",
    "scan web results",
    "search the web",
]


@dataclass
class CompareRequest:
    raw_text: str
    query: str
    vendors: List[str]
    include_web_search: bool
    output_path: Path


@dataclass
class Row:
    store: str
    product: str
    price: str
    shipping: str
    total: str
    link: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _cache_file() -> Path:
    return Path.home() / ".chintu" / "price_compare_cache.json"


def _cache_key(request: CompareRequest) -> str:
    query_key = re.sub(r"\s+", " ", request.query.strip().lower())
    vendors_key = ",".join(sorted(v.strip().lower() for v in request.vendors))
    return f"{query_key}::{vendors_key}"


def _row_has_price(row: Row) -> bool:
    return bool(str(row.price or "").strip().startswith("$")) and str(row.total or "").strip().startswith("$")


def _rows_have_real_prices(rows: List[Row]) -> bool:
    return any(_row_has_price(row) for row in rows)


def _serialize_rows(rows: List[Row]) -> List[Dict[str, str]]:
    payload: List[Dict[str, str]] = []
    for row in rows:
        payload.append(
            {
                "store": row.store,
                "product": row.product,
                "price": row.price,
                "shipping": row.shipping,
                "total": row.total,
                "link": row.link,
            }
        )
    return payload


def _deserialize_rows(items: List[Dict[str, str]]) -> List[Row]:
    out: List[Row] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            Row(
                store=str(item.get("store") or "").strip() or "Unknown",
                product=str(item.get("product") or "").strip() or "Unknown",
                price=str(item.get("price") or "").strip() or "n/a",
                shipping=str(item.get("shipping") or "").strip() or "n/a",
                total=str(item.get("total") or "").strip() or "n/a",
                link=str(item.get("link") or "").strip() or "n/a",
            )
        )
    return out


def _load_cache() -> Dict[str, Dict[str, object]]:
    path = _cache_file()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return {}
    return entries


def _save_cache(entries: Dict[str, Dict[str, object]]) -> None:
    path = _cache_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"updated_at": _now_iso(), "entries": entries}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _load_cached_rows(request: CompareRequest, max_age_hours: int = CACHE_MAX_AGE_HOURS) -> Optional[List[Row]]:
    entries = _load_cache()
    if not entries:
        return None
    key = _cache_key(request)
    item = entries.get(key)
    if not isinstance(item, dict):
        return None
    updated_at = str(item.get("updated_at") or "").strip()
    if updated_at:
        try:
            ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
            if age_seconds > max(1, int(max_age_hours)) * 3600:
                return None
        except Exception:
            pass
    rows_raw = item.get("rows")
    if not isinstance(rows_raw, list):
        return None
    rows = _deserialize_rows(rows_raw)
    if not _rows_have_real_prices(rows):
        return None
    return rows


def _store_cached_rows(request: CompareRequest, rows: List[Row]) -> None:
    if not _rows_have_real_prices(rows):
        return
    entries = _load_cache()
    key = _cache_key(request)
    entries[key] = {
        "updated_at": _now_iso(),
        "query": request.query,
        "vendors": list(request.vendors),
        "rows": _serialize_rows(rows),
    }
    _save_cache(entries)


def _to_ascii(value: str) -> str:
    return str(value or "").encode("ascii", errors="ignore").decode("ascii")


def _extract_filename(text: str) -> Optional[str]:
    backticks = re.findall(r"`([^`]+\.md)`", text, flags=re.IGNORECASE)
    if backticks:
        return backticks[-1].strip()

    quotes = re.findall(r'"([^"]+\.md)"', text, flags=re.IGNORECASE)
    if quotes:
        return quotes[-1].strip()

    simple = re.findall(r"\bas\s+([a-zA-Z0-9._\\/\-]+\.md)\b", text, flags=re.IGNORECASE)
    if simple:
        return simple[-1].strip()
    return None


def _extract_output_path(text: str) -> Path:
    filename_or_path = _extract_filename(text) or DEFAULT_OUTPUT
    candidate = Path(filename_or_path).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        return candidate

    lowered = text.lower()
    if "downloads" in lowered:
        root = Path.home() / "Downloads"
    elif "documents" in lowered:
        root = Path.home() / "Documents"
    else:
        root = Path.home() / "Desktop"
    return root / candidate.name


def _extract_vendors(text: str) -> Tuple[List[str], bool]:
    lowered = text.lower()
    vendors: List[str] = []
    for vendor, aliases in VENDOR_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            vendors.append(vendor)
    broad_compare = any(signal in lowered for signal in BROAD_SITE_SIGNALS)
    include_web = any(signal in lowered for signal in WEB_EXPANSION_SIGNALS)
    if broad_compare and vendors:
        for vendor in DEFAULT_VENDORS:
            if vendor not in vendors:
                vendors.append(vendor)
    if not vendors:
        vendors = list(DEFAULT_VENDORS)
    return vendors, include_web


def _strip_vendor_trailing_bits(text: str) -> str:
    cleaned = re.sub(
        r"\b(on|across|from|at)\s+(amazon|newegg|best\s*buy|bestbuy|walmart|b&h|bhphoto|"
        r"bh\s*photo|micro\s*center|microcenter|other\s+sites|other\s+websites|all\s+sites)"
        r"(?:[\s,]*(and|or)?[\s,]*(amazon|newegg|best\s*buy|bestbuy|walmart|b&h|bhphoto|"
        r"bh\s*photo|micro\s*center|microcenter|other\s+sites|other\s+websites|all\s+sites))*.*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b(create|save|write)\b.*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" .,:;\"'")


def _extract_query(text: str) -> str:
    lowered = text.lower()
    patterns = [
        r"(?:best\s+price|find\s+the\s+best\s+price)\s+(?:for|on)\s+(.+)",
        r"(?:compare|comparison)\s+(?:price|prices)?\s*(?:for|of)?\s+(.+)",
        r"price\s+compare\s+(?:for|of)?\s+(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        if match:
            start, end = match.span(1)
            return _strip_vendor_trailing_bits(text[start:end])

    fallback = re.sub(r"\b(compare|price|prices|find|best|deal|table|markdown)\b", "", text, flags=re.IGNORECASE)
    fallback = _strip_vendor_trailing_bits(fallback)
    fallback = re.sub(r"\s+", " ", fallback).strip()
    return fallback


def _parse_request(raw_text: str) -> CompareRequest:
    text = raw_text.strip()
    vendors, include_web = _extract_vendors(text)
    query = _extract_query(text)
    if not query:
        query = "consumer product"
    query = re.sub(r"^\s*(a|an|the)\s+", "", query, flags=re.IGNORECASE).strip()
    output_path = _extract_output_path(text)
    return CompareRequest(
        raw_text=text,
        query=_to_ascii(query),
        vendors=vendors,
        include_web_search=include_web,
        output_path=output_path,
    )


def _money(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"${float(value):,.2f}"


def _fetch_text(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }
    candidates = [
        f"https://r.jina.ai/http://{url.replace('https://', '').replace('http://', '')}",
        url,
    ]
    for candidate in candidates:
        try:
            response = requests.get(candidate, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.text or ""
        except Exception:
            continue
    return ""


def _infer_shipping_speed(url: str, cache: Dict[str, str]) -> str:
    domain = urlparse(url).netloc.lower().replace("www.", "")
    if not domain:
        domain = url
    if domain in cache:
        return cache[domain]

    text = _fetch_text(url)
    lowered = text.lower()
    speed = "Shipping details unavailable"
    markers = [
        ("same day", "Same-day delivery"),
        ("same-day", "Same-day delivery"),
        ("overnight", "Overnight shipping"),
        ("next day", "Next-day shipping"),
        ("next-day", "Next-day shipping"),
        ("2-day", "2-day shipping"),
        ("two-day", "2-day shipping"),
        ("3-5 business day", "3-5 business days"),
        ("5-7 business day", "5-7 business days"),
        ("free shipping", "Free shipping"),
        ("standard shipping", "Standard shipping"),
    ]
    for needle, label in markers:
        if needle in lowered:
            speed = label
            break

    cache[domain] = speed
    return speed


def _pick_best_per_vendor(vendors: List[str], listings) -> Dict[str, object]:
    best: Dict[str, object] = {}
    domain_vendor_map = {
        "amazon.com": "amazon",
        "newegg.com": "newegg",
        "bestbuy.com": "bestbuy",
        "walmart.com": "walmart",
        "bhphotovideo.com": "bhphoto",
        "microcenter.com": "microcenter",
    }
    for item in listings:
        vendor_raw = str(getattr(item, "vendor", "") or "").strip().lower()
        vendor = vendor_raw
        if vendor_raw.startswith("web:"):
            domain = vendor_raw.split(":", 1)[1].strip().lower()
            for known_domain, known_vendor in domain_vendor_map.items():
                if domain == known_domain or domain.endswith("." + known_domain):
                    vendor = known_vendor
                    break
        if vendor not in vendors:
            continue
        total = getattr(item, "total", None)
        if total is None:
            continue
        current = best.get(vendor)
        if current is None or float(getattr(current, "total", 1e18) or 1e18) > float(total):
            best[vendor] = item
    return best


def _render_markdown(rows: List[Row], query: str, vendors: List[str], include_web: bool) -> str:
    lines = [
        f"# Price Comparison: {query}",
        "",
        f"- Vendors scanned: {', '.join(vendors)}",
        f"- Trusted web expansion: {'enabled' if include_web else 'disabled'}",
        "",
        "| Store | Product | Price | Shipping Speed | Total | Link |",
        "| --- | --- | ---: | --- | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.store} | {row.product} | {row.price} | {row.shipping} | {row.total} | {row.link} |"
        )
    return "\n".join(lines)


def _build_rows(request: CompareRequest, per_vendor_best: Dict[str, object]) -> List[Row]:
    shipping_cache: Dict[str, str] = {}
    rows: List[Row] = []
    for vendor in request.vendors:
        listing = per_vendor_best.get(vendor)
        if listing is None:
            rows.append(
                Row(
                    store=vendor.title(),
                    product="No listing extracted",
                    price="n/a",
                    shipping="n/a",
                    total="n/a",
                    link="n/a",
                )
            )
            continue

        title = _to_ascii(str(getattr(listing, "title", "") or "")).replace("|", " ").strip()
        if len(title) > 80:
            title = title[:77].rstrip() + "..."
        url = _to_ascii(str(getattr(listing, "url", "") or "")).replace("|", "%7C").strip()
        shipping = _infer_shipping_speed(url, shipping_cache) if url and url != "n/a" else "n/a"

        rows.append(
            Row(
                store=vendor.title(),
                product=title or request.query,
                price=_money(getattr(listing, "price", None)),
                shipping=_to_ascii(shipping),
                total=_money(getattr(listing, "total", None)),
                link=url or "n/a",
            )
        )
    return rows


def run_comparison(raw_text: str) -> Tuple[CompareRequest, List[Row], Dict[str, str]]:
    request = _parse_request(raw_text)
    vendors, _, errors, combined = run_deal_finder(
        query=request.query,
        vendors=request.vendors,
        max_results_per_vendor=6,
        include_web_search=request.include_web_search,
        max_web_results=8,
        # Allow browser-based fallback when direct HTTP scraping is blocked.
        # This keeps the skill usable even when anti-bot pages appear.
        enable_playwright_fallback=True,
    )
    per_vendor_best = _pick_best_per_vendor(vendors, combined)
    rows = _build_rows(request, per_vendor_best)

    # Reliability upgrade: if a requested vendor is missing and web expansion was not explicitly
    # requested, perform one bounded retry with trusted web expansion enabled.
    missing_vendors = [row.store.lower() for row in rows if row.total == "n/a" and row.price == "n/a"]
    if missing_vendors and not request.include_web_search:
        vendors2, _, errors2, combined2 = run_deal_finder(
            query=request.query,
            vendors=request.vendors,
            max_results_per_vendor=8,
            include_web_search=True,
            max_web_results=12,
            enable_playwright_fallback=True,
        )
        per_vendor_best2 = _pick_best_per_vendor(vendors2, combined2)
        rows2 = _build_rows(request, per_vendor_best2)
        # Prefer retry result when it improves vendor coverage.
        old_with_price = sum(1 for row in rows if _row_has_price(row))
        new_with_price = sum(1 for row in rows2 if _row_has_price(row))
        if new_with_price >= old_with_price:
            rows = rows2
        if errors2:
            errors = {**errors, **errors2}
        errors.setdefault(
            "auto_retry",
            "Performed one trusted web expansion retry because one or more requested vendors returned no priced listings.",
        )

    if _rows_have_real_prices(rows):
        try:
            _store_cached_rows(request, rows)
        except Exception:
            pass
    else:
        cached = _load_cached_rows(request)
        if cached:
            rows = cached
            errors["cache"] = "Live vendor fetch failed. Showing last known comparison from local cache."

    # Do not report vendor errors when final table already includes a valid priced row for that vendor.
    resolved_vendors = {str(row.store or "").strip().lower() for row in rows if _row_has_price(row)}
    for key in list(errors.keys()):
        if str(key or "").strip().lower() in resolved_vendors:
            errors.pop(key, None)
    return request, rows, errors


def main() -> None:
    raw_request = " ".join(sys.argv[1:]).strip()
    request, rows, errors = run_comparison(raw_request)

    markdown = _render_markdown(
        rows=rows,
        query=request.query,
        vendors=request.vendors,
        include_web=request.include_web_search,
    )
    request.output_path.parent.mkdir(parents=True, exist_ok=True)
    request.output_path.write_text(markdown, encoding="utf-8")

    print(f"Comparing prices for: {request.query}")
    print(f"Vendors: {', '.join(request.vendors)}")
    print(f"Saved comparison table to {request.output_path}\n")
    print(markdown)
    if errors:
        print("\nNotes:")
        for vendor, err in errors.items():
            if vendor in request.vendors:
                print(f"- {vendor}: {_to_ascii(err)}")


if __name__ == "__main__":
    main()
