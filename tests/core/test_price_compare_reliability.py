from __future__ import annotations

from chintu_backend.automation.deal_finder_capabilities import DealListing, fetch_amazon_listings
from skills.price_compare import compare_prices as cp


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = int(status_code)
        self.text = text


def test_fetch_amazon_listings_uses_playwright_on_retryable_http(monkeypatch):
    monkeypatch.setattr(
        "chintu_backend.automation.deal_finder_capabilities._fetch_with_requests_retries",
        lambda *args, **kwargs: (_FakeResponse(503, ""), ""),
    )
    monkeypatch.setattr(
        "chintu_backend.automation.deal_finder_capabilities._try_fetch_html_playwright_dual",
        lambda *args, **kwargs: ("<html>ok</html>", ""),
    )
    monkeypatch.setattr(
        "chintu_backend.automation.deal_finder_capabilities._looks_blocked_amazon",
        lambda html: False,
    )
    monkeypatch.setattr(
        "chintu_backend.automation.deal_finder_capabilities._parse_amazon_search_html",
        lambda *args, **kwargs: [
            DealListing(
                vendor="amazon",
                title="Example Product",
                price=123.45,
                shipping=None,
                url="https://www.amazon.com/dp/B000000001",
                meta={},
            )
        ],
    )

    listings, err = fetch_amazon_listings("test query", max_results=3, enable_playwright_fallback=True)
    assert not err
    assert len(listings) == 1
    assert listings[0].vendor == "amazon"
    assert listings[0].meta.get("source") == "playwright"


def test_run_comparison_auto_retry_promotes_web_vendor_match(monkeypatch):
    calls: list[bool] = []

    def _fake_run_deal_finder(*, query, vendors, max_results_per_vendor, include_web_search, max_web_results, enable_playwright_fallback):
        calls.append(bool(include_web_search))
        if not include_web_search:
            return (
                list(vendors),
                {},
                {"amazon": "Amazon returned HTTP 503"},
                [
                    DealListing(
                        vendor="newegg",
                        title="Newegg Product",
                        price=199.99,
                        shipping=0.0,
                        url="https://www.newegg.com/p/abc123",
                        meta={},
                    )
                ],
            )
        return (
            list(vendors) + ["web"],
            {},
            {},
            [
                DealListing(
                    vendor="web:amazon.com",
                    title="Amazon Product via Web",
                    price=189.99,
                    shipping=0.0,
                    url="https://www.amazon.com/dp/B000000002",
                    meta={},
                ),
                DealListing(
                    vendor="newegg",
                    title="Newegg Product",
                    price=199.99,
                    shipping=0.0,
                    url="https://www.newegg.com/p/abc123",
                    meta={},
                ),
            ],
        )

    monkeypatch.setattr(cp, "run_deal_finder", _fake_run_deal_finder)

    request, rows, errors = cp.run_comparison(
        "Find the best price for Samsung 990 Pro 2TB on Amazon and Newegg and save as `ssd_prices.md`."
    )

    assert request.query
    assert calls == [False, True]
    by_store = {row.store.lower(): row for row in rows}
    assert by_store["amazon"].price.startswith("$")
    assert by_store["newegg"].price.startswith("$")
    assert "amazon" not in errors
    assert "auto_retry" in errors
