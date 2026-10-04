"""IBKR Flex Web Service client and Flex statement parser.

The TWS API ``reqExecutions`` only exposes the *current day's* executions
(Interactive Brokers docs: "Only the current day's executions can be
retrieved"). To retrieve historical trades (generally up to 365 days)
Interactive Brokers provides the Flex Web Service: a Flex Query is configured
in Account Management (Performance & Reports -> Flex Queries), then this
module submits the request, polls for the generated statement and parses the
Trade Confirmations section.

Documentation:
    https://ibkrcampus.com/docs/docs/web-api/flex-web-service/

This module also parses Flex statements exported manually from the Client
Portal (Performance & Reports -> Flex Queries -> Run -> download). Such files
can be fed to :func:`parse_flex_statement`, which accepts the XML export
(recommended, same ``FlexQueryResponse`` root as IBKR) and, best-effort, a
Flex CSV export.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime

import requests
from pydantic import BaseModel

LIVE_HOST = "https://ndcdyn.interactivebrokers.com"
PAPER_HOST = "https://gdcdyn.interactivebrokers.com"
_SEND_PATH = "/AccountManagement/FlexWebService/SendRequest"
_GET_PATH = "/AccountManagement/FlexWebService/GetStatement"
_API_VERSION = "3"

_NOT_READY_CODE = "1019"

_DATETIME_FORMATS = (
    "%Y%m%d;%H%M%S",
    "%Y-%m-%d;%H%M%S",
    "%Y%m%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y%m%d",
    "%Y-%m-%d",
)

_SIDE_MAP = {"BUY": "BOT", "BOT": "BOT", "SELL": "SLD", "SLD": "SLD"}


class FlexConfig(BaseModel):
    """Configuration for the IBKR Flex Web Service, read from the environment."""

    token: str
    query_id: str
    paper: bool = False
    timeout: int = 30
    poll_attempts: int = 6
    poll_interval: float = 5.0

    @classmethod
    def from_env(cls) -> "FlexConfig | None":
        """Build the config from ``IBKR_FLEX_*`` env vars, or return None if unset."""
        token = os.getenv("IBKR_FLEX_TOKEN", "").strip()
        query_id = os.getenv("IBKR_FLEX_QUERY_ID", "").strip()
        if not token or not query_id:
            return None
        paper = os.getenv("IBKR_FLEX_PAPER", "").strip().lower() in {"1", "true", "yes"}
        return cls(token=token, query_id=query_id, paper=paper)

    @property
    def host(self) -> str:
        """Flex Web Service host for the selected account type."""
        return PAPER_HOST if self.paper else LIVE_HOST


class FlexExecution(BaseModel):
    """A single executed trade normalised from a Flex Trade Confirmation."""

    exec_id: str
    time: datetime
    symbol: str = ""
    sec_type: str = ""
    currency: str = ""
    expiry: str = ""
    strike: float = 0.0
    right: str = ""
    side: str = ""
    shares: float = 0.0
    price: float = 0.0
    commission: float = 0.0
    realized_pnl: float = 0.0
    exchange: str = ""
    account: str = ""


def _local_tag(element: ET.Element) -> str:
    """Return the tag name without any XML namespace prefix."""
    return element.tag.rsplit("}", 1)[-1]


def _to_float(value: object) -> float:
    """Best-effort conversion to float, tolerating empty/None/grouped values."""
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _parse_flex_datetime(date_str: str, time_str: str = "") -> datetime | None:
    """Parse a Flex date/time pair across the formats IB emits."""
    date_str = (date_str or "").strip()
    time_str = (time_str or "").strip()
    candidates: list[str] = []
    if date_str and time_str:
        candidates.extend((f"{date_str};{time_str}", f"{date_str} {time_str}"))
    if date_str:
        candidates.append(date_str)
    for value in candidates:
        for fmt in _DATETIME_FORMATS:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


_OCC_RE_PADDED = re.compile(r"^([A-Z0-9]+)\s+(\d{6})([CP])(\d{8})$")
_OCC_RE_COMPACT = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def _parse_occ_symbol(symbol: str) -> tuple[str, str, str, float] | None:
    """Parse an OCC option symbol.

    Handles both the padded form (``AMD   261218P00300000``) and the compact
    form (``AAPL251219C00150000``). Returns
    ``(underlying, expiry_yyyymmdd, right, strike)`` or ``None``.
    """
    text = (symbol or "").strip().upper()
    match = _OCC_RE_PADDED.match(text) or _OCC_RE_COMPACT.match(text)
    if not match:
        return None
    underlying, yymmdd, right, strike_raw = match.groups()
    try:
        expiry = datetime.strptime(yymmdd, "%y%m%d").strftime("%Y%m%d")
    except ValueError:
        return None
    return underlying, expiry, right, int(strike_raw) / 1000.0


def _enrich_option_fields(execution: FlexExecution) -> FlexExecution:
    """Derive strike/right/expiry (and clean symbol) from an OCC option symbol."""
    if execution.sec_type.upper() != "OPT":
        return execution
    if execution.strike and execution.right and execution.expiry:
        return execution
    parsed = _parse_occ_symbol(execution.symbol)
    if parsed is None:
        return execution
    underlying, expiry, right, strike = parsed
    return execution.model_copy(
        update={
            "symbol": underlying or execution.symbol,
            "expiry": execution.expiry or expiry,
            "right": execution.right or right,
            "strike": execution.strike or strike,
        }
    )


def _ensure_exec_ids(executions: list[FlexExecution]) -> list[FlexExecution]:
    """Guarantee a unique exec_id for every row.

    MEXEM/IBKR Flex exports have no execution-id attribute, so without this
    every row would share an empty id and the ledger de-duplication would
    collapse the whole file into a single trade. Missing ids get a stable
    synthetic key derived from the row content, with an occurrence suffix for
    genuinely identical rows.
    """
    occurrences: dict[str, int] = {}
    for execution in executions:
        exec_id = (execution.exec_id or "").strip()
        if exec_id and exec_id.lower() != "nan":
            continue
        base = "|".join(
            [
                execution.time.isoformat(),
                execution.symbol,
                execution.side,
                f"{execution.shares:g}",
                f"{execution.price:g}",
                f"{execution.commission:g}",
                execution.account,
            ]
        )
        seen = occurrences.get(base, 0) + 1
        occurrences[base] = seen
        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
        execution.exec_id = f"SYN-{digest}" + (f"-{seen}" if seen > 1 else "")
    return executions


def _parse_flex_envelope(text: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Parse a Flex service status response.

    Returns a tuple ``(status, reference_code, error_code, error_message)``.
    """
    root = ET.fromstring(text)
    status = reference = error_code = error_message = None
    for child in root:
        tag = _local_tag(child)
        if tag == "Status":
            status = child.text
        elif tag == "ReferenceCode":
            reference = child.text
        elif tag == "ErrorCode":
            error_code = child.text
        elif tag == "ErrorMessage":
            error_message = child.text
    return status, reference, error_code, error_message


def send_flex_request(config: FlexConfig) -> str:
    """Submit the Flex query and return its ReferenceCode."""
    url = config.host + _SEND_PATH
    response = requests.get(
        url,
        params={"t": config.token, "q": config.query_id, "v": _API_VERSION},
        timeout=config.timeout,
    )
    response.raise_for_status()
    status, reference, error_code, error_message = _parse_flex_envelope(response.text)
    if status != "Success" or not reference:
        raise RuntimeError(
            f"Flex SendRequest failed (status={status}, "
            f"code={error_code}, message={error_message})"
        )
    return reference


def fetch_flex_statement(config: FlexConfig) -> str:
    """Run the full Flex flow and return the generated XML statement."""
    reference = send_flex_request(config)
    url = config.host + _GET_PATH
    last_status = "unknown"
    for _ in range(config.poll_attempts):
        response = requests.get(
            url,
            params={"t": config.token, "q": reference, "v": _API_VERSION},
            timeout=config.timeout,
        )
        response.raise_for_status()
        text = response.text
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return text
        if _local_tag(root) != "FlexStatementResponse":
            return text
        status, _, error_code, error_message = _parse_flex_envelope(text)
        if error_code == _NOT_READY_CODE or status == "Warn":
            last_status = f"code={error_code}, message={error_message}"
            time.sleep(config.poll_interval)
            continue
        raise RuntimeError(
            f"Flex GetStatement failed (status={status}, "
            f"code={error_code}, message={error_message})"
        )
    raise TimeoutError(f"Flex statement not ready after {config.poll_attempts} polls ({last_status})")


def _parse_flex_xml(statement: str) -> list[FlexExecution]:
    """Parse the Trade Confirmations of a Flex XML statement."""
    try:
        root = ET.fromstring(statement)
    except ET.ParseError as exc:
        raise RuntimeError(f"XML Flex malformato: {exc}") from exc
    executions: list[FlexExecution] = []
    for element in root.iter():
        if _local_tag(element) != "Trade":
            continue
        attrs = element.attrib
        when = _parse_flex_datetime(attrs.get("dateTime", ""))
        if when is None:
            when = _parse_flex_datetime(attrs.get("tradeDate", ""), attrs.get("tradeTime", ""))
        if when is None:
            continue
        side_raw = (attrs.get("buySell") or attrs.get("side") or "").upper()
        execution = FlexExecution(
                exec_id=(
                    attrs.get("tradeID")
                    or attrs.get("ibExecID")
                    or attrs.get("execID")
                    or attrs.get("transactionID")
                    or ""
                ),
                time=when,
                symbol=attrs.get("symbol") or attrs.get("underlyingSymbol") or "",
                sec_type=attrs.get("assetCategory") or "",
                currency=attrs.get("currency") or "",
                expiry=attrs.get("expiry") or "",
                strike=_to_float(attrs.get("strike")),
                right=attrs.get("putCall") or "",
                side=_SIDE_MAP.get(side_raw, side_raw),
                shares=abs(_to_float(attrs.get("quantity"))),
                price=_to_float(attrs.get("tradePrice")),
                commission=_to_float(attrs.get("ibCommission")),
                realized_pnl=_to_float(
                    attrs.get("realizedPL")
                    or attrs.get("fifoPnlRealized")
                    or attrs.get("mtmPnl")
                ),
                exchange=attrs.get("exchange") or attrs.get("listingExchange") or "",
                account=attrs.get("accountId") or "",
            )
        executions.append(_enrich_option_fields(execution))
    return executions


_FIELD_SYNONYMS: dict[str, set[str]] = {
    "datetime": {"datetime", "tradedatetime", "executiontime", "lastexecutiontime"},
    "date": {"date", "tradedate"},
    "time": {"time", "tradetime", "executiontime"},
    "symbol": {"symbol", "underlyingsymbol", "localsymbol"},
    "side": {"buysell", "side", "transactiontype", "action"},
    "shares": {"quantity", "qty", "shares", "filledquantity"},
    "price": {"tradeprice", "price", "avgtradeprice", "avgprice"},
    "commission": {"ibcommission", "commission", "brokerage"},
    "realized_pnl": {"realizedpnl", "realizedpl", "fifopnlrealized", "mtmpnl"},
    "sec_type": {"assetclass", "assetcategory", "sectype", "securitytype"},
    "currency": {"currency", "currencyprimary"},
    "exchange": {"exchange", "listingexchange"},
    "account": {"clientaccountid", "accountid", "account", "accountnumber"},
    "exec_id": {"tradeid", "ibexecid", "execid", "transactionid"},
    "strike": {"strike"},
    "expiry": {"expiry", "expiration", "expirydate"},
    "right": {"putcall", "right", "optiontype"},
}


def _norm_key(name: str) -> str:
    """Normalise a column name for tolerant synonym matching."""
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _parse_flex_value_datetime(raw: str) -> datetime | None:
    """Parse a combined Flex date/time cell across separators."""
    cleaned = " ".join((raw or "").replace(",", " ").split())
    if not cleaned:
        return None
    return _parse_flex_datetime(cleaned, "")


def _csv_row_to_execution(row: dict[str, str]) -> FlexExecution | None:
    """Map a single CSV row to a FlexExecution, or None when unusable."""
    lookup = {_norm_key(key): (value or "").strip() for key, value in row.items()}

    def pick(field: str) -> str:
        for name in _FIELD_SYNONYMS[field]:
            value = lookup.get(name)
            if value:
                return value
        return ""

    when = _parse_flex_value_datetime(pick("datetime"))
    if when is None:
        when = _parse_flex_datetime(pick("date"), pick("time"))
    if when is None:
        return None
    symbol = pick("symbol")
    if not symbol:
        return None
    side_raw = pick("side").upper()
    execution = FlexExecution(
        exec_id=pick("exec_id"),
        time=when,
        symbol=symbol,
        sec_type=pick("sec_type"),
        currency=pick("currency"),
        expiry=pick("expiry"),
        strike=_to_float(pick("strike")),
        right=pick("right"),
        side=_SIDE_MAP.get(side_raw, side_raw),
        shares=abs(_to_float(pick("shares"))),
        price=_to_float(pick("price")),
        commission=_to_float(pick("commission")),
        realized_pnl=_to_float(pick("realized_pnl")),
        exchange=pick("exchange"),
        account=pick("account"),
    )
    return _enrich_option_fields(execution)


def _parse_flex_csv(content: str) -> list[FlexExecution]:
    """Best-effort parser for a Flex CSV export.

    Handles both the ``Section,Header``/``Section,Data`` layout used by Flex
    CSV exports and a plain single-header CSV. Returns the trades it can map;
    raises when the layout cannot be recognised.
    """
    reader = csv.reader(io.StringIO(content))
    headers: dict[str, list[str]] = {}
    rows: list[dict[str, str]] = []
    plain_header: list[str] | None = None
    symbol_keys = _FIELD_SYNONYMS["symbol"]

    for raw in reader:
        if not raw or all(not cell.strip() for cell in raw):
            continue
        first = raw[0].strip()
        if first in {"BOF", "EOF"}:
            continue
        if len(raw) >= 3 and raw[1].strip().lower() == "header":
            headers[first] = [cell.strip() for cell in raw[2:]]
            continue
        if len(raw) >= 3 and raw[1].strip().lower() == "data":
            section_header = headers.get(first)
            if not section_header:
                continue
            values = [cell.strip() for cell in raw[2:2 + len(section_header)]]
            rows.append(dict(zip(section_header, values)))
            continue
        if plain_header is None and any(_norm_key(cell) in symbol_keys for cell in raw):
            plain_header = [cell.strip() for cell in raw]
            continue
        if plain_header is not None:
            values = [cell.strip() for cell in raw[:len(plain_header)]]
            rows.append(dict(zip(plain_header, values)))

    if not rows:
        raise RuntimeError(
            "CSV Flex non riconosciuto: nessuna intestazione di trade trovata. "
            "Esporta l'estratto in formato XML (consigliato)."
        )
    executions = [execution for row in rows
                  if (execution := _csv_row_to_execution(row)) is not None]
    if not executions:
        raise RuntimeError(
            "CSV Flex riconosciuto ma senza operazioni valide (servono colonne "
            "Symbol e Data/Ora). Esporta l'estratto in formato XML."
        )
    return executions


def parse_flex_statement(content: str) -> list[FlexExecution]:
    """Parse a Flex statement into executions.

    Accepts a Flex XML export (the MEXEM/IBKR default, root
    ``FlexQueryResponse``) or, best-effort, a Flex CSV export. Raises a
    ``RuntimeError``/``ValueError`` with a clear reason when the content is
    empty, malformed or of an unrecognised layout.
    """
    if content is None:
        raise ValueError("Nessun contenuto da analizzare.")
    text = content.lstrip()
    if not text.strip():
        raise ValueError("Il file caricato è vuoto.")
    if text.startswith("<"):
        executions = _parse_flex_xml(text)
    else:
        executions = _parse_flex_csv(text)
    return _ensure_exec_ids(executions)


def parse_flex_trades(statement: str) -> list[FlexExecution]:
    """Backward-compatible alias of :func:`parse_flex_statement`."""
    return parse_flex_statement(statement)


def get_flex_executions(
    config: FlexConfig,
    start: date | None = None,
    end: date | None = None,
) -> list[dict]:
    """Fetch Flex trades, normalised to dicts and filtered by date range."""
    executions = parse_flex_statement(fetch_flex_statement(config))
    result: list[dict] = []
    for execution in executions:
        trade_date = execution.time.date()
        if start is not None and trade_date < start:
            continue
        if end is not None and trade_date > end:
            continue
        result.append(execution.model_dump())
    result.sort(key=lambda item: item["time"], reverse=True)
    return result
