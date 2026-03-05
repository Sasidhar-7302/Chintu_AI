"""Finance watchlist and analysis capabilities (read-only)."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType
from chintu_backend.core.config import get_config
from chintu_backend.research.verified_research import VerifiedResearcher
from .portfolio_manager import get_portfolio_manager
from .watchlist_store import get_watchlist_store, NAME_MAP, WatchItem

logger = logging.getLogger(__name__)


TRADE_KEYWORDS = {
    "buy",
    "sell",
    "swap",
    "bridge",
    "transfer",
    "send",
    "trade",
    "short",
    "long",
    "leverage",
    "deploy token",
    "mint",
    "bet",
    "stake",
    "withdraw",
    "place order",
    "execute order",
    "market order",
    "limit order",
    "payment",
    "pay",
    "checkout",
    "wire transfer",
    "ach transfer",
    "send money",
    "invest now",
}


def _trade_requested(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in TRADE_KEYWORDS)


def _extract_csv_path(text: str) -> str:
    candidates: List[str] = []
    patterns = [
        r"[`'\"]([^`'\"]+\.csv)[`'\"]",
        r"([A-Za-z]:\\[^\n\r]+?\.csv)",
        r"((?:\.\.?[\\/])?[^\s`'\"]+\.csv)",
    ]
    for pattern in patterns:
        candidates.extend(match.group(1).strip() for match in re.finditer(pattern, text or "", flags=re.IGNORECASE))
    if not candidates:
        return ""

    for candidate in candidates:
        cleaned = candidate.strip().strip(".,;)")
        path = Path(cleaned).expanduser()
        if path.exists():
            return str(path)
    return candidates[0].strip().strip(".,;)")


def _extract_labeled_number(text: str, labels: List[str]) -> Optional[float]:
    if not text:
        return None
    for label in labels:
        pattern = rf"{re.escape(label)}\s*(?:is|=|of|:)?\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return float(match.group(1).replace(",", ""))
        except Exception:
            continue
    return None


def _extract_currency(text: str) -> str:
    if not text:
        return "USD"
    match = re.search(r"\b(USD|EUR|GBP|INR|JPY|AED|AUD|CAD)\b", text, flags=re.IGNORECASE)
    if not match:
        return "USD"
    return match.group(1).upper()


def _format_money(value: float) -> str:
    return f"${float(value):,.2f}"


def _extract_assets(text: str) -> List[str]:
    if not text:
        return []
    tokens = set()
    # Explicit tickers like BTC, ETH, SOL, AAPL
    tokens.update(re.findall(r"\$?[A-Za-z]{2,6}", text))
    # Common names mapping
    lowered = text.lower()
    for name, ticker in NAME_MAP.items():
        if name in lowered:
            tokens.add(ticker)
    cleaned = []
    for tok in tokens:
        tok = tok.strip("$").upper()
        if len(tok) < 2:
            continue
        if tok in {
            "WITH",
            "THIS",
            "THAT",
            "WHAT",
            "FROM",
            "THE",
            "YOUR",
            "WANT",
            "NEED",
            "NOTE",
            "ADD",
            "MANUAL",
            "POSITION",
            "BALANCE",
            "ACCOUNT",
            "CASH",
        }:
            continue
        cleaned.append(tok)
    return sorted(set(cleaned))


def _interest_phrase(text: str) -> bool:
    lowered = (text or "").lower()
    phrases = [
        "interested in",
        "looking at",
        "keep an eye on",
        "watch",
        "tracking",
        "following",
        "researching",
    ]
    return any(p in lowered for p in phrases)


def capture_interest_candidates(text: str, source: str = "conversation") -> List[Dict[str, str]]:
    if _trade_requested(text):
        return []
    if not _interest_phrase(text):
        return []
    assets = _extract_assets(text)
    if not assets:
        return []
    store = get_watchlist_store()
    config = get_config()
    return store.add_candidates(
        assets,
        source=source,
        max_per_day=int(getattr(config, "finance_max_candidates_per_day", 3)),
    )


def _format_watchlist(items: List[WatchItem]) -> str:
    if not items:
        return "Your watchlist is empty."
    lines = ["Your watchlist:"]
    for item in items:
        lines.append(f"- {item.symbol} ({item.label}) [{item.asset_type}]")
    return "\n".join(lines)


def handle_watchlist_add(text: str, _context: Dict[str, Any]) -> ActionResult:
    if _trade_requested(text):
        return ActionResult.fail(
            "I won't execute trades or move funds. I can only add assets to the watchlist and analyze them.",
            "finance_watch_add",
        )
    assets = _extract_assets(text)
    if not assets:
        return ActionResult.fail("Tell me which assets to track (e.g., BTC, ETH).", "finance_watch_add")
    store = get_watchlist_store()
    added = store.add_items(assets, asset_type="crypto")
    if not added:
        return ActionResult.ok("Those assets are already in your watchlist.", capability="finance_watch_add")
    return ActionResult.ok(
        "Added to watchlist: " + ", ".join(item.symbol for item in added),
        {"added": [item.symbol for item in added]},
        "finance_watch_add",
    )


def handle_watchlist_remove(text: str, _context: Dict[str, Any]) -> ActionResult:
    assets = _extract_assets(text)
    if not assets:
        return ActionResult.fail("Tell me which assets to remove.", "finance_watch_remove")
    store = get_watchlist_store()
    removed = store.remove_items(assets)
    if not removed:
        return ActionResult.ok("None of those assets were on your watchlist.", capability="finance_watch_remove")
    return ActionResult.ok(
        "Removed from watchlist: " + ", ".join(removed),
        {"removed": removed},
        "finance_watch_remove",
    )


def handle_watchlist_list(_text: str, _context: Dict[str, Any]) -> ActionResult:
    store = get_watchlist_store()
    items = store.list_items()
    return ActionResult.ok(_format_watchlist(items), {"items": [i.to_dict() for i in items]}, "finance_watch_list")


def handle_candidates_list(_text: str, _context: Dict[str, Any]) -> ActionResult:
    store = get_watchlist_store()
    candidates = store.list_candidates()
    if not candidates:
        return ActionResult.ok("No pending candidates.", {"candidates": []}, "finance_candidates_list")
    lines = ["Pending candidates:"]
    for cand in candidates[:12]:
        rationale = cand.get("rationale") or ""
        suffix = f" - {rationale[:120]}" if rationale else ""
        lines.append(f"- {cand.get('symbol')} ({cand.get('label')}){suffix}")
    lines.append("Say: add candidate BTC to approve one.")
    return ActionResult.ok(
        "\n".join(lines),
        {"candidates": candidates},
        "finance_candidates_list",
    )


def handle_candidates_add(text: str, context: Dict[str, Any]) -> ActionResult:
    store = get_watchlist_store()
    assets = _extract_assets(text)
    if not assets:
        return ActionResult.fail("Tell me which candidate to add.", "finance_candidate_add")
    symbol = assets[0]

    def _do_add() -> ActionResult:
        added = store.promote_candidate(symbol)
        if not added:
            return ActionResult.fail("That candidate is not on the list.", "finance_candidate_add")
        return ActionResult.ok(
            f"Added {added.symbol} to your watchlist.",
            {"symbol": added.symbol},
            "finance_candidate_add",
        )

    if not context.get("_confirmed"):
        return ActionResult.confirm(f"Add {symbol} to your watchlist?", _do_add, "finance_candidate_add")
    return _do_add()


def handle_watchlist_profile(text: str, _context: Dict[str, Any]) -> ActionResult:
    store = get_watchlist_store()
    lowered = text.lower()
    risk = None
    horizon = None
    strategy = None
    notes = None

    match = re.search(r"risk(?: profile)?\s*(?:is|=)?\s*(low|moderate|medium|high)", lowered)
    if match:
        risk = match.group(1)
        if risk == "medium":
            risk = "moderate"

    match = re.search(r"horizon\s*(?:is|=)?\s*([a-z0-9\-\s]+)", lowered)
    if match:
        horizon = match.group(1).strip()[:80]

    match = re.search(r"strategy\s*(?:is|=)?\s*([a-z0-9\-\s]+)", lowered)
    if match:
        strategy = match.group(1).strip()[:80]

    match = re.search(r"notes?\s*(?:is|=)?\s*(.+)$", lowered)
    if match:
        notes = match.group(1).strip()[:200]

    if not any([risk, horizon, strategy, notes]):
        profile = store.get_profile()
        response = (
            "Finance profile:\n"
            f"- Risk profile: {profile.get('risk_profile')}\n"
            f"- Time horizon: {profile.get('time_horizon')}\n"
            f"- Strategy style: {profile.get('strategy_style')}\n"
            f"- Notes: {profile.get('notes') or 'None'}"
        )
        return ActionResult.ok(response, {"profile": profile}, "finance_watch_profile")

    profile = store.update_profile(
        risk_profile=risk,
        time_horizon=horizon,
        strategy_style=strategy,
        notes=notes,
    )
    return ActionResult.ok(
        "Updated finance profile.",
        {"profile": profile},
        "finance_watch_profile",
    )


def _build_analysis_prompt(
    items: List[WatchItem],
    profile: Dict[str, str],
    sources: List[Dict[str, str]],
) -> str:
    watchlist = ", ".join(item.symbol for item in items)
    source_lines = []
    for idx, src in enumerate(sources, start=1):
        title = src.get("title") or f"Source {idx}"
        url = src.get("url") or ""
        snippet = (src.get("snippet") or "").strip()
        source_lines.append(f"[{idx}] {title} - {url}\n{snippet}")
    source_block = "\n\n".join(source_lines) if source_lines else "No sources available."
    return f"""
You are Chintu's finance analyst. Provide educational market analysis only.
Do NOT give financial advice, explicit buy/sell calls, or price targets.
Always include risk warnings and uncertainties.

Watchlist: {watchlist}
User profile:
- Risk profile: {profile.get('risk_profile')}
- Time horizon: {profile.get('time_horizon')}
- Strategy style: {profile.get('strategy_style')}
- Notes: {profile.get('notes')}

Sources:
{source_block}

Return a concise brief with sections:
1) Market Summary (cite sources like [1])
2) Watchlist Signals (bullish/bearish factors, cite sources)
3) Strategy Ideas (educational only, no direct advice)
4) Risks & Unknowns
5) Questions for the user
Finish with: "Not financial advice."
""".strip()


def handle_finance_brief(text: str, context: Dict[str, Any]) -> ActionResult:
    if _trade_requested(text):
        return ActionResult.fail(
            "I won't execute trades or move funds. I can only provide analysis.",
            "finance_brief",
        )

    store = get_watchlist_store()
    items = store.list_items()
    if not items:
        return ActionResult.fail(
            "Your watchlist is empty. Add assets first (e.g., 'track BTC, ETH').",
            "finance_brief",
        )

    config = get_config()
    researcher = VerifiedResearcher()

    queries = [f"{item.symbol} price news outlook" for item in items[:6]]
    sources: List[Dict[str, str]] = []
    for query in queries:
        try:
            result = researcher.research(query, max_results=2)
            sources.extend(result.get("sources") or [])
        except Exception as exc:
            logger.warning("Research failed for %s: %s", query, exc)

    profile = store.get_profile()
    prompt = _build_analysis_prompt(items, profile, sources)

    response_text = ""
    try:
        from chintu_backend.core.model_router import get_router

        router = get_router()
        response_text, _source = router.route_and_execute(prompt)
    except Exception as exc:
        logger.warning("Finance brief LLM failed: %s", exc)

    if not response_text:
        response_text = (
            "Market analysis is unavailable right now. Here are the sources I gathered:\n"
            + "\n".join(f"- {src.get('title')} ({src.get('url')})" for src in sources[:8])
            + "\n\nNot financial advice."
        )

    brief_path = store.record_brief("Daily Finance Brief", response_text, sources)
    footer = f"\n\nSaved brief: {brief_path}"

    return ActionResult.ok(
        response_text + footer,
        {"brief_path": str(brief_path), "sources": sources},
        "finance_brief",
    )


def _build_news_prompt(
    focus: str,
    regions: List[str],
    sources: List[Dict[str, str]],
    max_candidates: int,
) -> str:
    source_lines = []
    for idx, src in enumerate(sources, start=1):
        title = src.get("title") or f"Source {idx}"
        url = src.get("url") or ""
        snippet = (src.get("snippet") or "").strip()
        source_lines.append(f"[{idx}] {title} - {url}\n{snippet}")
    source_block = "\n\n".join(source_lines) if source_lines else "No sources available."
    return f"""
You are a market scout. Based ONLY on the sources, propose up to {max_candidates} watchlist candidates.
Focus assets: {focus}. Regions: {', '.join(regions)}.
Return JSON array with fields: symbol, name, region, rationale, source_indexes (list of ints).
Do not include trading instructions.
Sources:
{source_block}
""".strip()


def _parse_candidate_json(text: str) -> List[Dict[str, str]]:
    if not text:
        return []
    try:
        import json

        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            payload = json.loads(text[start : end + 1])
            if isinstance(payload, list):
                return [c for c in payload if isinstance(c, dict)]
    except Exception:
        return []
    return []


def handle_finance_news_pulse(text: str, _context: Dict[str, Any]) -> ActionResult:
    if _trade_requested(text):
        return ActionResult.fail(
            "I won't execute trades or move funds. I can only provide analysis.",
            "finance_news_pulse",
        )

    config = get_config()
    focus = getattr(config, "finance_asset_focus", "both")
    regions = [r.strip().lower() for r in getattr(config, "finance_regions", "us,india").split(",") if r.strip()]
    max_candidates = int(getattr(config, "finance_max_candidates_per_day", 3))

    researcher = VerifiedResearcher()
    queries: List[str] = []
    if focus in {"both", "crypto"}:
        queries.append("crypto market movers today")
    if focus in {"both", "stocks"}:
        if "us" in regions:
            queries.append("US stock market movers today")
        if "india" in regions:
            queries.append("India stock market movers today")

    sources: List[Dict[str, str]] = []
    for query in queries:
        try:
            result = researcher.research(query, max_results=3)
            sources.extend(result.get("sources") or [])
        except Exception as exc:
            logger.warning("Finance pulse research failed: %s", exc)

    prompt = _build_news_prompt(focus, regions or ["global"], sources, max_candidates)
    response_text = ""
    candidates: List[Dict[str, str]] = []
    try:
        from chintu_backend.core.model_router import get_router

        router = get_router()
        response_text, _source = router.route_and_execute(prompt)
        candidates = _parse_candidate_json(response_text)
    except Exception as exc:
        logger.warning("Finance pulse LLM failed: %s", exc)

    store = get_watchlist_store()
    added_candidates = store.add_candidates(
        candidates if candidates else [],
        source="news_pulse",
        max_per_day=max_candidates,
    )

    lines = ["Market pulse summary (analysis only)."]
    if sources:
        lines.append(f"Sources collected: {len(sources)}")
    if added_candidates:
        lines.append("Suggested candidates (pending approval):")
        for cand in added_candidates:
            rationale = cand.get("rationale") or ""
            lines.append(f"- {cand.get('symbol')} ({cand.get('label')}): {rationale[:120]}")
        lines.append("Say: add candidate SYMBOL to approve.")
    else:
        lines.append("No new candidates today.")
    lines.append("Not financial advice.")

    return ActionResult.ok(
        "\n".join(lines),
        {"sources": sources, "candidates": added_candidates},
        "finance_news_pulse",
    )


def handle_finance_schedule(text: str, context: Dict[str, Any]) -> ActionResult:
    if _trade_requested(text):
        return ActionResult.fail(
            "I won't execute trades or move funds. Scheduling is only for analysis.",
            "finance_schedule_brief",
        )

    from chintu_backend.core.scheduler import get_scheduler
    from chintu_backend.automation.scheduled_tasks import parse_schedule, ScheduleType

    config = get_config()
    schedule_params = parse_schedule(text)
    if not schedule_params:
        schedule_params = {
            "schedule_type": ScheduleType.DAILY,
            "schedule_time": getattr(config, "finance_daily_brief_time", "09:00"),
        }
    schedule_type = schedule_params["schedule_type"]
    schedule_time = schedule_params["schedule_time"]
    schedule_day = schedule_params.get("schedule_day")

    scheduler = get_scheduler()
    command_handler = context.get("command_handler")
    if command_handler:
        scheduler.set_callback(command_handler.handle)
    scheduler.start()

    task = scheduler.schedule(
        name="Finance Daily Brief",
        workflow="finance brief",
        schedule_type=schedule_type,
        schedule_time=schedule_time,
        schedule_day=schedule_day,
    )

    return ActionResult.ok(
        f"Scheduled finance brief: {schedule_type.value} at {schedule_time}.",
        {"task_id": task.id, "schedule": task.schedule_type.value},
        "finance_schedule_brief",
    )


def handle_finance_schedule_pulse(text: str, context: Dict[str, Any]) -> ActionResult:
    if _trade_requested(text):
        return ActionResult.fail(
            "I won't execute trades or move funds. Scheduling is only for analysis.",
            "finance_schedule_pulse",
        )
    from chintu_backend.core.scheduler import get_scheduler
    from chintu_backend.automation.scheduled_tasks import parse_schedule, ScheduleType

    config = get_config()
    schedule_params = parse_schedule(text)
    if not schedule_params:
        schedule_params = {
            "schedule_type": ScheduleType.DAILY,
            "schedule_time": getattr(config, "finance_daily_brief_time", "08:00"),
        }
    schedule_type = schedule_params["schedule_type"]
    schedule_time = schedule_params["schedule_time"]
    schedule_day = schedule_params.get("schedule_day")

    scheduler = get_scheduler()
    command_handler = context.get("command_handler")
    if command_handler:
        scheduler.set_callback(command_handler.handle)
    scheduler.start()

    task = scheduler.schedule(
        name="Finance Daily Pulse",
        workflow="finance news pulse",
        schedule_type=schedule_type,
        schedule_time=schedule_time,
        schedule_day=schedule_day,
    )

    return ActionResult.ok(
        f"Scheduled finance pulse: {schedule_type.value} at {schedule_time}.",
        {"task_id": task.id, "schedule": task.schedule_type.value},
        "finance_schedule_pulse",
    )


def _render_portfolio_summary(summary: Dict[str, Any]) -> List[str]:
    metrics = summary.get("metrics", {})
    lines = [
        "Portfolio summary (read-only):",
        f"- Positions: {metrics.get('positions_count', 0)}",
        f"- Cash accounts: {metrics.get('cash_accounts_count', 0)}",
        f"- Total portfolio value: {_format_money(metrics.get('total_portfolio_value', 0.0))}",
        f"- Positions value: {_format_money(metrics.get('positions_value', 0.0))}",
        f"- Cash value: {_format_money(metrics.get('cash_value', 0.0))}",
        f"- Peak value: {_format_money(metrics.get('peak_value', 0.0))}",
        f"- Drawdown from peak: {metrics.get('drawdown_pct', 0.0)}%",
        f"- Concentration: {metrics.get('concentration', 'unknown')}",
    ]
    if metrics.get("unrealized_pnl") is not None:
        lines.append(
            f"- Unrealized PnL: {_format_money(metrics.get('unrealized_pnl', 0.0))} "
            f"({metrics.get('unrealized_return_pct', 0.0)}%)"
        )
    lines.append("")
    lines.append("Top allocations:")
    allocations = summary.get("allocations", [])
    if not allocations:
        lines.append("- No positions available yet.")
    else:
        for item in allocations[:6]:
            lines.append(
                f"- {item.get('symbol')}: {item.get('allocation_pct', 0.0)}% "
                f"({_format_money(item.get('market_value', 0.0))})"
            )
    return lines


def _parse_manual_entry(text: str) -> Dict[str, Any]:
    lowered = (text or "").lower()
    currency = _extract_currency(text)

    if any(
        token in lowered
        for token in ["cash account", "bank account", "cash balance", "account balance", "add cash", "cash entry"]
    ):
        account_match = re.search(
            r"(?:account|cash account|bank account)\s*(?:is|=|named|:)?\s*([a-zA-Z0-9 _-]{2,50})",
            text or "",
            flags=re.IGNORECASE,
        )
        account = account_match.group(1).strip() if account_match else "Cash"
        balance = _extract_labeled_number(
            text,
            ["balance", "cash", "amount", "value", "cash value", "account balance"],
        )
        return {
            "entry_type": "cash",
            "account": account,
            "balance": balance,
            "currency": currency,
        }

    symbol = ""
    for token in re.findall(r"\b[A-Z]{2,6}\b", text or ""):
        if token in {"ADD", "MANUAL", "POSITION", "VALUE", "COST", "BASIS", "CASH", "ACCOUNT"}:
            continue
        symbol = token
        break
    if not symbol:
        assets = _extract_assets(text)
        symbol = assets[0] if assets else ""
    quantity = _extract_labeled_number(text, ["quantity", "qty", "shares", "units"])
    if quantity is None:
        loose_match = re.search(r"(\d+(?:\.\d+)?)\s+([A-Za-z]{2,8})", text or "")
        if loose_match:
            quantity = float(loose_match.group(1))
            if not symbol:
                symbol = loose_match.group(2).upper()
    market_value = _extract_labeled_number(
        text,
        ["market value", "position value", "value", "worth", "current value"],
    )
    price = _extract_labeled_number(text, ["price", "entry price", "current price"])
    if market_value is None and quantity is not None and price is not None:
        market_value = quantity * price
    cost_basis = _extract_labeled_number(
        text,
        ["cost basis", "cost", "basis", "invested", "principal"],
    ) or 0.0
    return {
        "entry_type": "position",
        "symbol": symbol,
        "quantity": quantity,
        "market_value": market_value,
        "cost_basis": cost_basis,
        "currency": currency,
    }


def handle_finance_portfolio_import(text: str, context: Dict[str, Any]) -> ActionResult:
    if _trade_requested(text):
        return ActionResult.fail(
            "I won't execute trades or move funds. I can only import and analyze your portfolio data.",
            "finance_portfolio_import",
        )
    params = context.get("_validated_params") or context.get("_extracted_params") or {}
    csv_path = ""
    source_type = "auto"
    if isinstance(params, dict):
        csv_path = str(params.get("csv_path") or "").strip()
        source_type = str(params.get("source_type") or "auto").strip().lower()
    csv_path = csv_path or _extract_csv_path(text)
    if not csv_path:
        return ActionResult.fail(
            "Please provide a CSV path (broker or bank export), e.g., import portfolio from `C:\\\\path\\\\portfolio.csv`.",
            "finance_portfolio_import",
        )
    lowered = (text or "").lower()
    if source_type == "auto":
        if "bank" in lowered:
            source_type = "bank"
        elif "broker" in lowered or "portfolio" in lowered:
            source_type = "broker"

    manager = get_portfolio_manager()
    try:
        import_result = manager.import_csv(csv_path, source_type=source_type)
    except Exception as exc:
        return ActionResult.fail(f"Portfolio import failed: {exc}", "finance_portfolio_import")

    summary = manager.compute_summary()
    receipt_path = manager.write_receipt(
        title="Finance Portfolio Import Receipt",
        summary=summary,
        sources=[str(import_result.get("path"))],
        assumptions=[
            "Import workflow is read-only with respect to broker/bank systems.",
            "CSV rows with missing required fields are rejected and logged.",
            "Analytics are informational; no trades/payments are executed.",
        ],
    )
    lines = [
        "Imported portfolio data.",
        f"- CSV: {import_result.get('path')}",
        f"- Type: {import_result.get('source_type')}",
        f"- Accepted rows: {import_result.get('accepted_rows', 0)}",
        f"- Rejected rows: {import_result.get('rejected_rows', 0)}",
    ]
    if import_result.get("errors"):
        lines.append("- Rejection notes:")
        lines.extend([f"  - {entry}" for entry in import_result.get("errors", [])[:5]])
    lines.append(f"Saved receipt: {receipt_path}")
    lines.append("No transaction actions were executed.")
    return ActionResult.ok(
        "\n".join(lines),
        {
            "import": import_result,
            "summary": summary,
            "receipt_path": str(receipt_path),
        },
        "finance_portfolio_import",
    )


def handle_finance_portfolio_manual_entry(text: str, _context: Dict[str, Any]) -> ActionResult:
    if _trade_requested(text):
        return ActionResult.fail(
            "I won't execute trades or move funds. I can only store manual portfolio entries for analysis.",
            "finance_portfolio_manual_entry",
        )

    manager = get_portfolio_manager()
    parsed = _parse_manual_entry(text)
    entry: Dict[str, Any]
    if parsed.get("entry_type") == "cash":
        balance = parsed.get("balance")
        if balance is None:
            return ActionResult.fail(
                "For cash entries, include a balance like: cash account checking balance 2500 USD.",
                "finance_portfolio_manual_entry",
            )
        entry = manager.add_manual_cash_account(
            account=str(parsed.get("account") or "Cash"),
            balance=float(balance),
            currency=str(parsed.get("currency") or "USD"),
            notes="manual_entry",
        )
        message = (
            f"Added/updated cash account {entry.get('account')} with balance "
            f"{_format_money(entry.get('balance', 0.0))} {entry.get('currency', 'USD')}."
        )
    else:
        symbol = str(parsed.get("symbol") or "").strip().upper()
        market_value = parsed.get("market_value")
        if not symbol or market_value is None:
            return ActionResult.fail(
                "For positions, include symbol and value, e.g., add 2 BTC with value 120000 and cost basis 90000.",
                "finance_portfolio_manual_entry",
            )
        entry = manager.add_manual_position(
            symbol=symbol,
            quantity=float(parsed.get("quantity") or 0.0),
            market_value=float(market_value),
            cost_basis=float(parsed.get("cost_basis") or 0.0),
            currency=str(parsed.get("currency") or "USD"),
            notes="manual_entry",
        )
        message = (
            f"Added/updated position {entry.get('symbol')} with value "
            f"{_format_money(entry.get('market_value', 0.0))}."
        )

    summary = manager.compute_summary()
    receipt_path = manager.write_receipt(
        title="Finance Manual Portfolio Entry",
        summary=summary,
        sources=["manual user entry"],
    )
    return ActionResult.ok(
        f"{message}\nSaved receipt: {receipt_path}\nNo transaction actions were executed.",
        {"entry": entry, "summary": summary, "receipt_path": str(receipt_path)},
        "finance_portfolio_manual_entry",
    )


def handle_finance_portfolio_summary(text: str, _context: Dict[str, Any]) -> ActionResult:
    if _trade_requested(text):
        return ActionResult.fail(
            "I won't execute trades or move funds. I can only summarize your portfolio.",
            "finance_portfolio_summary",
        )
    manager = get_portfolio_manager()
    summary = manager.compute_summary()
    metrics = summary.get("metrics", {})
    if int(metrics.get("positions_count", 0)) == 0 and int(metrics.get("cash_accounts_count", 0)) == 0:
        return ActionResult.fail(
            "Portfolio is empty. Import broker/bank CSVs or add manual entries first.",
            "finance_portfolio_summary",
        )

    receipt_path = manager.write_receipt(
        title="Finance Portfolio Summary",
        summary=summary,
        sources=[entry.get("path", "") for entry in summary.get("imports", []) if entry.get("path")],
    )
    lines = _render_portfolio_summary(summary)
    lines.append("")
    lines.append(f"Saved receipt: {receipt_path}")
    lines.append("No transaction actions were executed.")
    return ActionResult.ok(
        "\n".join(lines),
        {"summary": summary, "receipt_path": str(receipt_path)},
        "finance_portfolio_summary",
    )


def handle_finance_portfolio_rebalance_plan(text: str, _context: Dict[str, Any]) -> ActionResult:
    if _trade_requested(text):
        return ActionResult.fail(
            "I won't execute trades or move funds. I can only provide a draft rebalance plan.",
            "finance_portfolio_rebalance_plan",
        )
    manager = get_portfolio_manager()
    summary = manager.compute_summary()
    metrics = summary.get("metrics", {})
    if int(metrics.get("positions_count", 0)) == 0:
        return ActionResult.fail(
            "No positions found. Import portfolio data first, then ask for a rebalance plan.",
            "finance_portfolio_rebalance_plan",
        )

    config = get_config()
    max_single = float(getattr(config, "finance_rebalance_max_single_position_pct", 40.0))
    suggestions = manager.build_rebalance_suggestions(summary, max_single_position_pct=max_single)
    checklist = [
        "Validate target allocations against your risk profile and tax constraints.",
        "Review fees/spreads in your broker before placing any order.",
        "Execute any trades manually in your broker app (Chintu does not trade).",
        "Re-import fresh CSVs after manual updates.",
    ]
    receipt_path = manager.write_receipt(
        title="Finance Rebalance Draft Plan",
        summary=summary,
        sources=[entry.get("path", "") for entry in summary.get("imports", []) if entry.get("path")],
        checklist=checklist,
        assumptions=[
            "This is a read-only planning draft with no order execution.",
            f"Single-position concentration target is <= {max_single:.1f}%.",
            "Manual broker confirmation is required for any real-world action.",
        ],
    )

    lines = ["Draft rebalance plan (read-only):"]
    if not suggestions:
        lines.append(f"- No position currently exceeds the {max_single:.1f}% concentration threshold.")
    else:
        for suggestion in suggestions:
            lines.append(
                f"- {suggestion.get('symbol')}: reduce by about {_format_money(suggestion.get('trim_amount_usd', 0.0))} "
                f"to move from {suggestion.get('current_allocation_pct', 0.0)}% to <= {suggestion.get('target_max_pct', max_single)}%."
            )
    lines.append("")
    lines.append("Manual checklist:")
    for item in checklist:
        lines.append(f"- [ ] {item}")
    lines.append("")
    lines.append(f"Saved receipt: {receipt_path}")
    lines.append("No transaction actions were executed.")

    return ActionResult.ok(
        "\n".join(lines),
        {"summary": summary, "suggestions": suggestions, "receipt_path": str(receipt_path)},
        "finance_portfolio_rebalance_plan",
    )


def register_finance_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="finance_watch_add",
            triggers=[
                "add to watchlist",
                "track asset",
                "track coin",
                "track token",
                "watch asset",
                "watch coin",
                "watch token",
            ],
            handler=handle_watchlist_add,
            requires_confirmation=False,
            description="add assets to a finance watchlist",
            capability_type=CapabilityType.PRODUCTIVITY,
        )
    )

    registry.register(
        Capability(
            name="finance_watch_remove",
            triggers=[
                "remove from watchlist",
                "untrack",
                "stop tracking",
                "remove asset",
            ],
            handler=handle_watchlist_remove,
            requires_confirmation=False,
            description="remove assets from the watchlist",
            capability_type=CapabilityType.PRODUCTIVITY,
        )
    )

    registry.register(
        Capability(
            name="finance_watch_list",
            triggers=[
                "show watchlist",
                "list watchlist",
                "my watchlist",
                "tracked assets",
            ],
            handler=handle_watchlist_list,
            requires_confirmation=False,
            description="list tracked assets",
            capability_type=CapabilityType.PRODUCTIVITY,
        )
    )

    registry.register(
        Capability(
            name="finance_candidates_list",
            triggers=[
                "show candidates",
                "list candidates",
                "pending candidates",
                "suggested candidates",
            ],
            handler=handle_candidates_list,
            requires_confirmation=False,
            description="list suggested watchlist candidates",
            capability_type=CapabilityType.PRODUCTIVITY,
        )
    )

    registry.register(
        Capability(
            name="finance_candidate_add",
            triggers=[
                "add candidate",
                "approve candidate",
                "add suggested",
            ],
            handler=handle_candidates_add,
            requires_confirmation=False,
            description="approve a suggested watchlist candidate",
            capability_type=CapabilityType.PRODUCTIVITY,
        )
    )

    registry.register(
        Capability(
            name="finance_watch_profile",
            triggers=[
                "finance profile",
                "investment profile",
                "risk profile",
                "set risk",
                "set horizon",
                "set strategy",
            ],
            handler=handle_watchlist_profile,
            requires_confirmation=False,
            description="set finance analysis preferences",
            capability_type=CapabilityType.PRODUCTIVITY,
        )
    )

    registry.register(
        Capability(
            name="finance_portfolio_import",
            triggers=[
                "import portfolio csv",
                "import broker csv",
                "import bank csv",
                "load portfolio csv",
                "portfolio import",
            ],
            handler=handle_finance_portfolio_import,
            requires_confirmation=False,
            description="import broker/bank csv data into read-only portfolio store",
            capability_type=CapabilityType.PRODUCTIVITY,
        )
    )

    registry.register(
        Capability(
            name="finance_portfolio_manual_entry",
            triggers=[
                "add manual position",
                "add manual cash account",
                "manual portfolio entry",
                "update portfolio manually",
            ],
            handler=handle_finance_portfolio_manual_entry,
            requires_confirmation=False,
            description="add manual read-only portfolio entries",
            capability_type=CapabilityType.PRODUCTIVITY,
        )
    )

    registry.register(
        Capability(
            name="finance_portfolio_summary",
            triggers=[
                "portfolio summary",
                "finance portfolio summary",
                "show portfolio summary",
                "portfolio analytics",
            ],
            handler=handle_finance_portfolio_summary,
            requires_confirmation=False,
            description="summarize portfolio allocations, pnl, drawdown, and concentration",
            capability_type=CapabilityType.AI_AGENT,
        )
    )

    registry.register(
        Capability(
            name="finance_portfolio_rebalance_plan",
            triggers=[
                "rebalance plan",
                "portfolio rebalance plan",
                "draft rebalance",
                "rebalancing suggestions",
            ],
            handler=handle_finance_portfolio_rebalance_plan,
            requires_confirmation=False,
            description="draft a read-only rebalance plan with manual checklist",
            capability_type=CapabilityType.AI_AGENT,
        )
    )

    registry.register(
        Capability(
            name="finance_brief",
            triggers=[
                "finance brief",
                "market brief",
                "daily finance brief",
                "crypto brief",
                "watchlist analysis",
            ],
            handler=handle_finance_brief,
            requires_confirmation=False,
            description="generate a read-only finance analysis brief",
            capability_type=CapabilityType.AI_AGENT,
        )
    )

    registry.register(
        Capability(
            name="finance_news_pulse",
            triggers=[
                "finance news pulse",
                "market pulse",
                "news pulse",
                "today movers",
                "market movers",
            ],
            handler=handle_finance_news_pulse,
            requires_confirmation=False,
            description="scan news for fast-moving market items and suggest candidates",
            capability_type=CapabilityType.AI_AGENT,
        )
    )

    registry.register(
        Capability(
            name="finance_schedule_brief",
            triggers=[
                "schedule finance brief",
                "schedule market brief",
                "daily finance brief at",
                "set finance brief",
            ],
            handler=handle_finance_schedule,
            requires_confirmation=True,
            description="schedule a daily finance analysis brief",
            capability_type=CapabilityType.PRODUCTIVITY,
        )
    )

    registry.register(
        Capability(
            name="finance_schedule_pulse",
            triggers=[
                "schedule market pulse",
                "schedule news pulse",
                "schedule finance pulse",
                "daily market pulse at",
            ],
            handler=handle_finance_schedule_pulse,
            requires_confirmation=True,
            description="schedule a daily finance market pulse",
            capability_type=CapabilityType.PRODUCTIVITY,
        )
    )
