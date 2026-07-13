#!/usr/bin/env python3
"""
Export IBKR portfolio positions to CSV.

Connects to TWS/IB Gateway via the existing IBKRConnector,
fetches all positions (stocks, options, etc.), and writes
them to a timestamped CSV file for offline analysis.

Usage:
    python export_positions.py                            # default 7497 (TWS paper)
    python export_positions.py --port 7496                # TWS live
    python export_positions.py --port 4002                # IB Gateway paper
    python export_positions.py --port 4001                # IB Gateway live
    python export_positions.py --output my_positions.csv  # custom CSV path
    python export_positions.py --help                     # full options
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ─── Pydantic Models ─────────────────────────────────────────────────────────


class PositionModel(BaseModel):
    """Normalised portfolio position row ready for CSV export."""

    symbol: str = Field(..., description="Ticker symbol")
    sec_type: str = Field(..., alias="sec_type", description="Security type (STK, OPT, FUT, …)")
    currency: str = Field(default="USD")
    exchange: str = Field(default="SMART")
    position: float = Field(..., description="Net position (+ long / − short)")
    market_price: float = Field(default=0.0, alias="market_price")
    market_value: float = Field(default=0.0, alias="market_value")
    average_cost: float = Field(default=0.0, alias="average_cost")
    cost_basis: float = Field(default=0.0, alias="cost_basis")
    unrealized_pnl: float = Field(default=0.0, alias="unrealized_pnl")
    realized_pnl: float = Field(default=0.0, alias="realized_pnl")
    account: str = Field(default="")
    expiry: str = Field(default="", description="Option expiry (YYYYMMDD)")
    strike: float = Field(default=0.0, description="Option strike price")
    right: str = Field(default="", description="Option right (C/P)")
    multiplier: str = Field(default="")

    @field_validator("symbol", mode="before")
    @classmethod
    def strip_symbol(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else str(v)

    @property
    def is_option(self) -> bool:
        return str(self.sec_type).upper() == "OPT"

    model_config = {"populate_by_name": True}


class PositionsExport(BaseModel):
    """Container for the full export."""

    exported_at: datetime = Field(default_factory=datetime.now)
    positions: list[PositionModel] = Field(default_factory=list)
    source: str = "IBKR (ib_async)"

    @property
    def total_market_value(self) -> float:
        return sum(p.market_value for p in self.positions)

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions)


# ─── CSV Writer ──────────────────────────────────────────────────────────────


CSV_FIELDS = [
    "symbol",
    "sec_type",
    "currency",
    "exchange",
    "position",
    "market_price",
    "market_value",
    "average_cost",
    "cost_basis",
    "unrealized_pnl",
    "realized_pnl",
    "account",
    "expiry",
    "strike",
    "right",
    "multiplier",
]


def write_csv(
    export: PositionsExport,
    path: Path,
    *,
    verbose: bool = True,
) -> Path:
    """Write the export to a CSV file. Returns the path written."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for pos in export.positions:
            writer.writerow(pos.model_dump(by_alias=True))

    if verbose:
        n = len(export.positions)
        print(f"📄 Written {n} position{'s' if n != 1 else ''} → {path}")
        print(f"   Market value:  ${export.total_market_value:,.2f}")
        print(f"   Unrealized P&L: ${export.total_unrealized_pnl:+,.2f}")

    return path


# ─── CLI ─────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export IBKR portfolio positions to CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7497,
        help=(
            "API port. Common values:\n"
            "  TWS:       7497 (paper) / 7496 (live)\n"
            "  IB Gateway: 4002 (paper) / 4001 (live)\n"
            "  (default: 7497)"
        ),
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="TWS/IB Gateway host (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--client-id",
        type=int,
        default=1,
        help="Client ID for TWS/IB Gateway (default: 1).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Connection timeout in seconds (default: 15).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="",
        help=(
            "Output CSV path. Auto-generates with timestamp when omitted, "
            "e.g. positions_20260706_1430.csv"
        ),
    )
    parser.add_argument(
        "--account",
        type=str,
        default="",
        help="IBKR account ID filter (e.g. DU123456). Leave empty for default.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=True,
        help="Print summary after export (default: on).",
    )
    return parser


def _resolve_output_path(custom: str) -> Path:
    if custom:
        p = Path(custom)
        if p.suffix.lower() != ".csv":
            p = p.with_suffix(".csv")
        return p
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(f"positions_{timestamp}.csv")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # ── Lazy import (saves startup if script is just --help) ─────────
    try:
        from ibkr_connector import IBKRConnector
    except ImportError as exc:
        print(f"❌ Cannot import IBKRConnector: {exc}", file=sys.stderr)
        print("   Run this script from the IBKR_Trading directory.", file=sys.stderr)
        return 1

    # ── Connect ──────────────────────────────────────────────────────
    connector = IBKRConnector()
    print(f"🔌 Connecting to IBKR at {args.host}:{args.port} …")
    try:
        connector.connect(
            host=args.host,
            port=args.port,
            clientId=args.client_id,
            timeout=args.timeout,
        )
    except ConnectionError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    # ── Fetch positions ──────────────────────────────────────────────
    print("📡 Fetching portfolio positions …")
    try:
        raw_positions: list[dict[str, Any]] = connector.get_positions(
            account=args.account
        )
    except (ConnectionError, ValueError, RuntimeError) as exc:
        print(f"❌ Failed to fetch positions: {exc}", file=sys.stderr)
        connector.disconnect()
        return 1
    finally:
        connector.disconnect()

    if not raw_positions:
        print("ℹ️  No positions found in the portfolio.")
        return 0

    # ── Validate via Pydantic ────────────────────────────────────────
    positions = [PositionModel(**p) for p in raw_positions]
    export = PositionsExport(positions=positions, exported_at=datetime.now())

    # ── Write CSV ────────────────────────────────────────────────────
    out_path = _resolve_output_path(args.output)
    write_csv(export, out_path, verbose=args.verbose)

    # ── Quick summary table ──────────────────────────────────────────
    stocks = [p for p in positions if not p.is_option]
    opts = [p for p in positions if p.is_option]

    print(f"\n📊 Summary: {len(stocks)} stock(s), {len(opts)} option(s)")
    if stocks:
        print(f"   Stock MV:    ${sum(s.market_value for s in stocks):,.2f}")
    if opts:
        print(f"   Options MV:  ${sum(o.market_value for o in opts):,.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
