"""Read-only portfolio ingestion, analytics, and receipt generation."""

from __future__ import annotations

import csv
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return cleaned or "receipt"


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "").replace("$", "")
    try:
        return float(text)
    except ValueError:
        return None


def _round_money(value: float) -> float:
    return round(float(value), 2)


DEFAULT_PORTFOLIO: Dict[str, Any] = {
    "positions": [],
    "cash_accounts": [],
    "imports": [],
    "snapshots": [],
    "last_updated": None,
}


class PortfolioManager:
    """Persistent portfolio data with normalized CSV import and analytics."""

    def __init__(self, path: Optional[Path] = None, receipts_dir: Optional[Path] = None) -> None:
        cfg = get_config()
        self.path = Path(path or cfg.finance_portfolio_store_path)
        self.receipts_dir = Path(receipts_dir or cfg.finance_receipts_dir)
        self._lock = Lock()
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        self._data = raw
                except Exception as exc:
                    logger.warning("Failed to load portfolio store: %s", exc)
            if not self._data:
                self._data = dict(DEFAULT_PORTFOLIO)
            for key, default_value in DEFAULT_PORTFOLIO.items():
                if key not in self._data:
                    self._data[key] = default_value

    def _save(self) -> None:
        with self._lock:
            self._data["last_updated"] = _now_iso()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    @staticmethod
    def _resolve_header_map(fieldnames: List[str]) -> Dict[str, str]:
        return {_normalize_header(name): name for name in fieldnames if name}

    @staticmethod
    def _field(row: Dict[str, Any], headers: Dict[str, str], candidates: List[str]) -> str:
        for key in candidates:
            original = headers.get(_normalize_header(key))
            if not original:
                continue
            value = row.get(original)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    def _upsert_position(
        self,
        *,
        symbol: str,
        quantity: float,
        market_value: float,
        cost_basis: float,
        currency: str,
        asset_type: str,
        source: str,
        notes: str = "",
    ) -> None:
        normalized_symbol = symbol.strip().upper()
        normalized_currency = (currency or "USD").strip().upper()
        for position in self._data.get("positions", []):
            if (
                str(position.get("symbol", "")).upper() == normalized_symbol
                and str(position.get("currency", "USD")).upper() == normalized_currency
            ):
                position["quantity"] = _round_money(float(position.get("quantity", 0.0)) + quantity)
                position["market_value"] = _round_money(float(position.get("market_value", 0.0)) + market_value)
                position["cost_basis"] = _round_money(float(position.get("cost_basis", 0.0)) + cost_basis)
                position["source"] = source
                position["asset_type"] = asset_type or position.get("asset_type") or "security"
                position["as_of"] = _now_iso()
                if notes:
                    position["notes"] = notes
                return

        self._data.setdefault("positions", []).append(
            {
                "symbol": normalized_symbol,
                "quantity": _round_money(quantity),
                "market_value": _round_money(market_value),
                "cost_basis": _round_money(cost_basis),
                "currency": normalized_currency,
                "asset_type": asset_type or "security",
                "source": source,
                "as_of": _now_iso(),
                "notes": notes or "",
            }
        )

    def _upsert_cash_account(
        self,
        *,
        account: str,
        balance: float,
        currency: str,
        source: str,
        notes: str = "",
    ) -> None:
        normalized_account = (account or "cash").strip()
        normalized_currency = (currency or "USD").strip().upper()
        for cash in self._data.get("cash_accounts", []):
            if (
                str(cash.get("account", "")).lower() == normalized_account.lower()
                and str(cash.get("currency", "USD")).upper() == normalized_currency
            ):
                cash["balance"] = _round_money(balance)
                cash["source"] = source
                cash["as_of"] = _now_iso()
                if notes:
                    cash["notes"] = notes
                return
        self._data.setdefault("cash_accounts", []).append(
            {
                "account": normalized_account,
                "balance": _round_money(balance),
                "currency": normalized_currency,
                "source": source,
                "as_of": _now_iso(),
                "notes": notes or "",
            }
        )

    def add_manual_position(
        self,
        *,
        symbol: str,
        quantity: float,
        market_value: float,
        cost_basis: float = 0.0,
        currency: str = "USD",
        asset_type: str = "security",
        notes: str = "",
    ) -> Dict[str, Any]:
        self._upsert_position(
            symbol=symbol,
            quantity=max(0.0, quantity),
            market_value=max(0.0, market_value),
            cost_basis=max(0.0, cost_basis),
            currency=currency,
            asset_type=asset_type,
            source="manual",
            notes=notes,
        )
        self._save()
        self._record_snapshot()
        return {
            "symbol": symbol.strip().upper(),
            "quantity": _round_money(quantity),
            "market_value": _round_money(market_value),
            "cost_basis": _round_money(cost_basis),
            "currency": currency.upper(),
        }

    def add_manual_cash_account(
        self,
        *,
        account: str,
        balance: float,
        currency: str = "USD",
        notes: str = "",
    ) -> Dict[str, Any]:
        self._upsert_cash_account(
            account=account,
            balance=balance,
            currency=currency,
            source="manual",
            notes=notes,
        )
        self._save()
        self._record_snapshot()
        return {"account": account, "balance": _round_money(balance), "currency": currency.upper()}

    def _detect_csv_type(self, headers: Dict[str, str], requested_type: str) -> str:
        requested = (requested_type or "auto").strip().lower()
        if requested in {"broker", "bank"}:
            return requested

        normalized = set(headers.keys())
        if normalized.intersection({"symbol", "ticker", "security", "asset", "marketvalue", "shares"}):
            return "broker"
        if normalized.intersection({"account", "accountname", "balance", "currentbalance"}):
            return "bank"
        return "unknown"

    def _parse_broker_row(self, row: Dict[str, Any], headers: Dict[str, str]) -> tuple[bool, str]:
        symbol = self._field(row, headers, ["symbol", "ticker", "security", "asset", "instrument"]).upper()
        market_value = _parse_float(
            self._field(
                row,
                headers,
                ["market_value", "marketvalue", "value", "current_value", "currentvalue", "amount", "equity"],
            )
        )
        quantity = _parse_float(self._field(row, headers, ["quantity", "qty", "shares", "units", "position"])) or 0.0
        cost_basis = _parse_float(
            self._field(
                row,
                headers,
                ["cost_basis", "costbasis", "cost", "book_value", "bookvalue", "invested", "principal"],
            )
        ) or 0.0
        currency = self._field(row, headers, ["currency", "ccy"]) or "USD"
        asset_type = self._field(row, headers, ["asset_type", "assettype", "type", "class"]) or "security"

        if not symbol:
            return False, "missing symbol"
        if market_value is None or market_value < 0:
            return False, "missing market value"

        self._upsert_position(
            symbol=symbol,
            quantity=quantity,
            market_value=market_value,
            cost_basis=max(0.0, cost_basis),
            currency=currency,
            asset_type=asset_type,
            source="csv",
        )
        return True, ""

    def _parse_bank_row(self, row: Dict[str, Any], headers: Dict[str, str]) -> tuple[bool, str]:
        account = self._field(row, headers, ["account", "account_name", "name", "bank_account"])
        balance = _parse_float(self._field(row, headers, ["balance", "current_balance", "amount", "available_balance"]))
        currency = self._field(row, headers, ["currency", "ccy"]) or "USD"

        if not account:
            return False, "missing account"
        if balance is None:
            return False, "missing balance"

        self._upsert_cash_account(
            account=account,
            balance=balance,
            currency=currency,
            source="csv",
        )
        return True, ""

    def import_csv(self, csv_path: str, source_type: str = "auto") -> Dict[str, Any]:
        path = Path(csv_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")
        if path.suffix.lower() != ".csv":
            raise ValueError("Only .csv files are supported.")

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("CSV file is missing headers.")
            headers = self._resolve_header_map(reader.fieldnames)
            detected = self._detect_csv_type(headers, source_type)
            if detected == "unknown":
                raise ValueError(
                    "Could not infer CSV type. Use broker-style (symbol/value) or bank-style (account/balance) columns."
                )

            accepted = 0
            rejected = 0
            errors: List[str] = []
            for index, row in enumerate(reader, start=2):
                if detected == "broker":
                    ok, reason = self._parse_broker_row(row, headers)
                else:
                    ok, reason = self._parse_bank_row(row, headers)
                if ok:
                    accepted += 1
                else:
                    rejected += 1
                    errors.append(f"row {index}: {reason}")

        import_entry = {
            "imported_at": _now_iso(),
            "source_type": detected,
            "path": str(path),
            "accepted_rows": accepted,
            "rejected_rows": rejected,
            "errors": errors[:20],
        }
        self._data.setdefault("imports", []).append(import_entry)
        self._save()
        self._record_snapshot()
        return import_entry

    def list_positions(self) -> List[Dict[str, Any]]:
        positions = [dict(item) for item in self._data.get("positions", []) if isinstance(item, dict)]
        positions.sort(key=lambda item: float(item.get("market_value", 0.0)), reverse=True)
        return positions

    def list_cash_accounts(self) -> List[Dict[str, Any]]:
        accounts = [dict(item) for item in self._data.get("cash_accounts", []) if isinstance(item, dict)]
        accounts.sort(key=lambda item: str(item.get("account", "")).lower())
        return accounts

    def list_imports(self) -> List[Dict[str, Any]]:
        entries = [dict(item) for item in self._data.get("imports", []) if isinstance(item, dict)]
        entries.sort(key=lambda item: str(item.get("imported_at", "")), reverse=True)
        return entries

    def _record_snapshot(self) -> None:
        summary = self.compute_summary()
        self._data.setdefault("snapshots", []).append(
            {
                "recorded_at": _now_iso(),
                "total_value": summary["metrics"]["total_portfolio_value"],
                "positions_value": summary["metrics"]["positions_value"],
                "cash_value": summary["metrics"]["cash_value"],
            }
        )
        self._data["snapshots"] = self._data["snapshots"][-365:]
        self._save()

    def _drawdown_from_snapshots(self, current_total: float) -> Dict[str, float]:
        snapshots = [s for s in self._data.get("snapshots", []) if isinstance(s, dict)]
        values = [float(s.get("total_value", 0.0)) for s in snapshots if float(s.get("total_value", 0.0)) > 0]
        if not values:
            return {"peak_value": _round_money(current_total), "drawdown_pct": 0.0}
        peak = max(values)
        drawdown_pct = 0.0 if peak <= 0 else round(((current_total - peak) / peak) * 100.0, 2)
        return {"peak_value": _round_money(peak), "drawdown_pct": drawdown_pct}

    @staticmethod
    def _concentration_label(max_alloc: float, hhi: float) -> str:
        if max_alloc >= 50.0 or hhi >= 0.35:
            return "high_concentration"
        if max_alloc >= 30.0 or hhi >= 0.20:
            return "moderate_concentration"
        return "diversified"

    def build_rebalance_suggestions(self, summary: Dict[str, Any], max_single_position_pct: float) -> List[Dict[str, Any]]:
        suggestions: List[Dict[str, Any]] = []
        total_value = float(summary["metrics"]["total_portfolio_value"])
        if total_value <= 0:
            return suggestions
        for item in summary.get("allocations", []):
            if item.get("symbol") == "CASH":
                continue
            alloc = float(item.get("allocation_pct", 0.0))
            if alloc <= max_single_position_pct:
                continue
            reduce_pct = round(alloc - max_single_position_pct, 2)
            trim_amount = round((reduce_pct / 100.0) * total_value, 2)
            suggestions.append(
                {
                    "symbol": item.get("symbol"),
                    "current_allocation_pct": alloc,
                    "target_max_pct": round(float(max_single_position_pct), 2),
                    "trim_amount_usd": trim_amount,
                }
            )
        return suggestions

    def compute_summary(self) -> Dict[str, Any]:
        positions = self.list_positions()
        accounts = self.list_cash_accounts()
        positions_value = sum(float(item.get("market_value", 0.0)) for item in positions)
        cash_value = sum(float(item.get("balance", 0.0)) for item in accounts)
        total_value = positions_value + cash_value

        allocations: List[Dict[str, Any]] = []
        if total_value > 0:
            for item in positions:
                pct = round((float(item.get("market_value", 0.0)) / total_value) * 100.0, 2)
                allocations.append(
                    {
                        "symbol": item.get("symbol"),
                        "allocation_pct": pct,
                        "market_value": _round_money(float(item.get("market_value", 0.0))),
                        "asset_type": item.get("asset_type", "security"),
                    }
                )
            if cash_value > 0:
                allocations.append(
                    {
                        "symbol": "CASH",
                        "allocation_pct": round((cash_value / total_value) * 100.0, 2),
                        "market_value": _round_money(cash_value),
                        "asset_type": "cash",
                    }
                )
        allocations.sort(key=lambda item: float(item.get("allocation_pct", 0.0)), reverse=True)

        total_cost = sum(max(float(item.get("cost_basis", 0.0)), 0.0) for item in positions)
        unrealized_pnl = None
        return_pct = None
        if total_cost > 0:
            unrealized_pnl = _round_money(positions_value - total_cost)
            return_pct = round((unrealized_pnl / total_cost) * 100.0, 2)

        non_cash_allocations = [float(item.get("allocation_pct", 0.0)) / 100.0 for item in allocations if item["symbol"] != "CASH"]
        hhi = round(sum(v * v for v in non_cash_allocations), 4) if non_cash_allocations else 0.0
        max_alloc = max((item.get("allocation_pct", 0.0) for item in allocations if item["symbol"] != "CASH"), default=0.0)
        concentration = self._concentration_label(float(max_alloc), hhi)
        drawdown = self._drawdown_from_snapshots(total_value)

        return {
            "positions": positions,
            "cash_accounts": accounts,
            "allocations": allocations,
            "metrics": {
                "positions_count": len(positions),
                "cash_accounts_count": len(accounts),
                "positions_value": _round_money(positions_value),
                "cash_value": _round_money(cash_value),
                "total_portfolio_value": _round_money(total_value),
                "total_cost_basis": _round_money(total_cost),
                "unrealized_pnl": unrealized_pnl,
                "unrealized_return_pct": return_pct,
                "peak_value": drawdown["peak_value"],
                "drawdown_pct": drawdown["drawdown_pct"],
                "hhi": hhi,
                "concentration": concentration,
            },
            "imports": self.list_imports()[:10],
            "generated_at": _now_iso(),
        }

    def write_receipt(
        self,
        *,
        title: str,
        summary: Dict[str, Any],
        assumptions: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
        checklist: Optional[List[str]] = None,
    ) -> Path:
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        receipt_path = self.receipts_dir / f"{stamp}_{_slugify(title)}.md"

        metrics = summary.get("metrics", {})
        lines = [
            f"# {title}",
            f"- Generated: {_now_iso()}",
            "",
            "## Portfolio Metrics",
            f"- Total portfolio value: ${metrics.get('total_portfolio_value', 0.0):,.2f}",
            f"- Positions value: ${metrics.get('positions_value', 0.0):,.2f}",
            f"- Cash value: ${metrics.get('cash_value', 0.0):,.2f}",
            f"- Unrealized PnL: {metrics.get('unrealized_pnl') if metrics.get('unrealized_pnl') is not None else 'n/a'}",
            f"- Unrealized return %: {metrics.get('unrealized_return_pct') if metrics.get('unrealized_return_pct') is not None else 'n/a'}",
            f"- Peak value: ${metrics.get('peak_value', 0.0):,.2f}",
            f"- Drawdown %: {metrics.get('drawdown_pct', 0.0)}",
            f"- Concentration: {metrics.get('concentration', 'unknown')}",
            "",
            "## Top Allocations",
        ]
        allocations = summary.get("allocations", [])
        if allocations:
            for item in allocations[:8]:
                lines.append(
                    f"- {item.get('symbol')}: {item.get('allocation_pct', 0.0)}% (${item.get('market_value', 0.0):,.2f})"
                )
        else:
            lines.append("- No allocation data.")

        lines.append("")
        lines.append("## Sources")
        if sources:
            for src in sources:
                lines.append(f"- {src}")
        else:
            lines.append("- Local portfolio store and imported CSV files.")

        lines.append("")
        lines.append("## Assumptions")
        for assumption in assumptions or [
            "All values are treated as USD unless CSV provided currency columns.",
            "Portfolio analytics are read-only and informational.",
            "No transaction or payment actions are executed by Chintu.",
        ]:
            lines.append(f"- {assumption}")

        lines.append("")
        lines.append("## Manual Checklist")
        for item in checklist or [
            "Review import rows for missing/incorrect symbols.",
            "Verify tax lots and fees in your broker dashboard.",
            "If rebalancing is desired, execute trades manually in your broker app.",
            "Re-import updated CSVs after manual changes.",
        ]:
            lines.append(f"- [ ] {item}")

        receipt_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return receipt_path


_manager: Optional[PortfolioManager] = None


def get_portfolio_manager() -> PortfolioManager:
    global _manager
    if _manager is None:
        _manager = PortfolioManager()
    return _manager
