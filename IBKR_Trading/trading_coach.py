"""AI Trading Coach: conversational capture of the user's trading style.

Talks to any OpenAI-compatible chat endpoint (configured from ``.env``),
persists a structured ``trading_profile.md`` and the chat in
``coach_history.json``. Network calls use ``requests`` and are isolated in
``_chat`` so they can be mocked in tests.
"""

from __future__ import annotations

import json
import os

import requests
from pydantic import BaseModel

PROFILE_FILENAME = "trading_profile.md"
HISTORY_FILENAME = "coach_history.json"

# provider -> (base_url, default_model, api-key env var)
PROVIDER_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "opencode-go": (
        "https://opencode.ai/zen/go/v1",
        "deepseek-v4.1-flash",
        "OPENCODE_GO_API_KEY",
    ),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "GROQ_API_KEY"),
    "openrouter": (
        "https://openrouter.ai/api/v1",
        "meta-llama/llama-3.3-70b-instruct",
        "OPENROUTER_API_KEY",
    ),
    "google": (
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-2.0-flash",
        "GOOGLE_API_KEY",
    ),
}

COACH_SYSTEM_PROMPT = (
    "Sei un Trading Coach esperto. Aiuti l'utente a descrivere, chiarire e "
    "strutturare il SUO stile di trading attraverso una conversazione. Fai "
    "domande di approfondimento mirate quando un punto è vago (entry/exit, "
    "gestione del rischio, sizing, strumenti, orari, criteri, errori da "
    "evitare). Rispondi in italiano, sii concreto e conciso. Non fornire "
    "consulenza finanziaria personalizzata né promesse di rendimento."
)

PROFILE_SYSTEM_PROMPT = (
    "Trasforma la conversazione fornita in un profilo di trading in Markdown, "
    "con queste sezioni: Regole di entry, Regole di exit, Gestione del rischio, "
    "Sizing, Strumenti preferiti, Orari, Criteri, Errori da evitare. Usa solo "
    "le informazioni emerse; se una sezione manca scrivi 'da definire'. Non "
    "inventare dati."
)

LEDGER_SYSTEM_PROMPT = (
    "Sei un Trading Coach. Ricevi le statistiche AGGREGATE dello storico "
    "operazioni dell'utente (nessun dato grezzo). Inferisci il suo stile di "
    "trading senza inventare nulla. Produci SOLO un profilo in Markdown con le "
    "sezioni: Regole di entry, Regole di exit, Gestione del rischio, Sizing, "
    "Strumenti preferiti, Orari, Criteri, Errori da evitare. In ogni sezione "
    "distingui esplicitamente i punti '✅ Dedotto dai dati' da quelli "
    "'❓ Da confermare con l'utente'. Non fornire consulenza finanziaria "
    "personalizzata né promesse di rendimento."
)


class CoachConfig(BaseModel):
    """Resolved OpenAI-compatible endpoint configuration."""

    provider: str = "opencode-go"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    timeout: int = 60
    temperature: float = 0.4

    @classmethod
    def from_env(cls, env: dict | None = None) -> "CoachConfig | None":
        """Build the config from env vars, or None when it cannot be resolved."""
        env = env if env is not None else os.environ
        provider = str(env.get("TRADING_COACH_PROVIDER", "")).strip().lower()
        base_url = str(env.get("TRADING_COACH_BASE_URL", "")).strip()
        model = str(env.get("TRADING_COACH_MODEL", "")).strip()
        api_key = str(env.get("TRADING_COACH_API_KEY", "")).strip()

        if not provider:
            provider = _guess_provider(env)
        base, default_model, key_env = PROVIDER_DEFAULTS.get(provider, ("", "", ""))
        base_url = base_url or base
        model = model or default_model
        api_key = api_key or str(env.get(key_env, "")).strip()

        if not (base_url and api_key and model):
            return None
        return cls(provider=provider or "custom", model=model, api_key=api_key, base_url=base_url)

    @property
    def chat_url(self) -> str:
        """Full chat-completions endpoint URL."""
        return self.base_url.rstrip("/") + "/chat/completions"


def _guess_provider(env: dict) -> str:
    """Pick the first provider with an API key present in the environment."""
    for provider, (_, _, key_env) in PROVIDER_DEFAULTS.items():
        if str(env.get(key_env, "")).strip():
            return provider
    return "opencode-go"


def _system_prompt(profile: str) -> str:
    """Coach system prompt, enriched with the saved profile when present."""
    prompt = COACH_SYSTEM_PROMPT
    if profile and profile.strip():
        prompt += "\n\n--- Profilo attuale dell'utente ---\n" + profile.strip()
    return prompt


def _estimate_holding_days(df) -> float | None:
    """Rough average holding period (days) from a netting pass over the ledger."""
    import pandas as pd

    if df is None or df.empty or "time" not in df.columns:
        return None
    work = df.copy()
    work["time"] = pd.to_datetime(work["time"], errors="coerce", utc=True)
    work = work.dropna(subset=["time"]).sort_values("time")
    if work.empty:
        return None
    for column in ("symbol", "sec_type", "expiry", "strike", "right", "side"):
        if column not in work.columns:
            work[column] = ""
    for column in ("shares", "price"):
        work[column] = (
            pd.to_numeric(work[column], errors="coerce").fillna(0.0)
            if column in work.columns
            else 0.0
        )

    state: dict[str, dict] = {}
    weighted_days = 0.0
    closed_qty = 0.0
    for _, row in work.iterrows():
        side = str(row["side"]).upper()
        if side not in {"BOT", "SLD", "BUY", "SELL"}:
            continue
        shares = abs(float(row["shares"]))
        if shares <= 0:
            continue
        key = f"{row['symbol']}|{row['sec_type']}|{row['expiry']}|{row['strike']}|{row['right']}"
        delta = shares if side in {"BOT", "BUY"} else -shares
        entry = state.setdefault(key, {"qty": 0.0, "opened": row["time"]})
        net = entry["qty"]
        if abs(net) <= 1e-9:
            entry["qty"], entry["opened"] = delta, row["time"]
        elif (net > 0) == (delta > 0):
            entry["qty"] = net + delta
        else:
            closing = min(abs(net), abs(delta))
            weighted_days += (row["time"] - entry["opened"]).days * closing
            closed_qty += closing
            new_net = net + delta
            if abs(new_net) <= 1e-9:
                entry["qty"] = 0.0
            elif (new_net > 0) == (net > 0):
                entry["qty"] = new_net
            else:
                entry["qty"], entry["opened"] = new_net, row["time"]

    return (weighted_days / closed_qty) if closed_qty > 0 else None


def _representative_trades(df, limit: int = 3) -> list[dict]:
    """Best/worst trades as illustrative samples (never the whole file)."""
    import pandas as pd

    if df is None or df.empty or "realized_pnl" not in df.columns:
        return []
    work = df.copy()
    work["_pnl"] = pd.to_numeric(work["realized_pnl"], errors="coerce").fillna(0.0)

    def _row_to_dict(record) -> dict:
        return {
            "date": str(record.get("time", "")),
            "symbol": str(record.get("symbol", "")),
            "side": str(record.get("side", "")),
            "shares": float(record.get("shares", 0) or 0),
            "price": float(record.get("price", 0) or 0),
            "pnl": round(float(record["_pnl"]), 2),
        }

    best = [_row_to_dict(r) for _, r in work.nlargest(limit, "_pnl").iterrows()]
    worst = [_row_to_dict(r) for _, r in work.nsmallest(limit, "_pnl").iterrows()]
    return best + worst


def build_ledger_summary(df, positions=None) -> dict:
    """Compact, structured summary of the ledger for the LLM (no raw dump)."""
    import pandas as pd

    from trade_stats import compute_trade_stats

    stats = compute_trade_stats(df)
    summary: dict = {
        "n_trades": stats.n_trades,
        "n_symbols": stats.n_symbols,
        "first_date": stats.first_date.strftime("%Y-%m-%d") if stats.first_date else None,
        "last_date": stats.last_date.strftime("%Y-%m-%d") if stats.last_date else None,
        "realized_pnl": round(stats.realized_pnl, 2),
        "net_pnl": round(stats.net_pnl, 2),
        "total_commission": round(stats.total_commission, 2),
        "win_rate_pct": round(stats.win_rate, 1),
        "profit_factor": round(stats.profit_factor, 2)
        if stats.profit_factor is not None
        else None,
        "avg_pnl_per_trade": round(stats.avg_pnl, 2),
        "n_wins": stats.n_wins,
        "n_losses": stats.n_losses,
        "n_flat": stats.n_flat,
        "long_short": {
            "BOT": {"n": stats.n_bot, "pnl": round(stats.pnl_bot, 2)},
            "SLD": {"n": stats.n_sld, "pnl": round(stats.pnl_sld, 2)},
        },
        "pnl_by_month": {item.period: round(item.realized_pnl, 2) for item in stats.by_month},
        "top_symbols_by_pnl": [
            {
                "symbol": item.symbol,
                "n": item.n_trades,
                "pnl": round(item.realized_pnl, 2),
                "win_rate": round(item.win_rate, 1),
            }
            for item in stats.by_symbol[:8]
        ],
    }

    if df is not None and not df.empty and "time" in df.columns:
        work = df.copy()
        work["time"] = pd.to_datetime(work["time"], errors="coerce", utc=True)
        work = work.dropna(subset=["time"])
        if not work.empty:
            sec = work.get("sec_type", pd.Series(dtype=str)).astype(str).str.upper()
            summary["sec_mix"] = {
                "STK": int((sec == "STK").sum()),
                "OPT": int((sec == "OPT").sum()),
            }
            shares = (
                pd.to_numeric(work.get("shares", pd.Series(dtype=float)), errors="coerce")
                .abs()
                .fillna(0.0)
            )
            price = pd.to_numeric(
                work.get("price", pd.Series(dtype=float)), errors="coerce"
            ).fillna(0.0)
            notionals = shares * price
            summary["avg_notional_per_trade"] = round(float(notionals.mean()), 2)
            summary["median_notional_per_trade"] = round(float(notionals.median()), 2)
            span_days = max((work["time"].max() - work["time"].min()).days, 1)
            summary["trades_per_week"] = round(len(work) / (span_days / 7.0), 2)
            summary["symbol_recurrence"] = (
                work.get("symbol", pd.Series(dtype=str))
                .astype(str)
                .value_counts()
                .head(8)
                .to_dict()
            )

    summary["holding_days_avg"] = _estimate_holding_days(df)
    if positions:
        summary["open_positions"] = [
            {
                "symbol": position.symbol,
                "sec_type": position.sec_type,
                "qty": position.quantity,
                "avg_cost": round(position.avg_cost, 4),
                "expiry": position.expiry,
                "strike": position.strike,
                "right": position.right,
            }
            for position in positions[:15]
        ]
    representatives = _representative_trades(df)
    if representatives:
        summary["representative_trades"] = representatives
    return summary


def format_ledger_summary(summary: dict) -> str:
    """Render the structured summary as an LLM-readable payload."""
    return (
        "Statistiche aggregate dello storico operazioni dell'utente "
        "(campione rappresentativo incluso):\n\n"
        + json.dumps(summary, ensure_ascii=False, indent=2)
    )


class TradingCoach:
    """Persistent coaching chat backed by an OpenAI-compatible LLM."""

    def __init__(self, config: CoachConfig, base_dir: str = ".") -> None:
        self.config = config
        self.base_dir = base_dir
        self.profile_path = os.path.join(base_dir, PROFILE_FILENAME)
        self.history_path = os.path.join(base_dir, HISTORY_FILENAME)

    # ── persistence ──
    def load_profile(self) -> str:
        if not os.path.isfile(self.profile_path):
            return ""
        try:
            with open(self.profile_path, encoding="utf-8") as fh:
                return fh.read()
        except OSError as e:
            print(f"[COACH] profile read failed: {e}")
            return ""

    def save_profile(self, text: str) -> None:
        with open(self.profile_path, "w", encoding="utf-8") as fh:
            fh.write(text or "")

    def clear_profile(self) -> None:
        if os.path.isfile(self.profile_path):
            os.remove(self.profile_path)

    def load_history(self) -> list[dict]:
        if not os.path.isfile(self.history_path):
            return []
        try:
            with open(self.history_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError) as e:
            print(f"[COACH] history read failed: {e}")
            return []

    def save_history(self, history: list[dict]) -> None:
        with open(self.history_path, "w", encoding="utf-8") as fh:
            json.dump(history, fh, ensure_ascii=False, indent=2)

    def clear_history(self) -> None:
        if os.path.isfile(self.history_path):
            os.remove(self.history_path)

    # ── LLM ──
    def _chat(self, messages: list[dict]) -> str:
        """Call the OpenAI-compatible chat endpoint and return the reply text."""
        response = requests.post(
            self.config.chat_url,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "messages": messages,
                "temperature": self.config.temperature,
            },
            timeout=self.config.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"]

    def reply(self, user_message: str) -> str:
        """Append the user message, get the assistant reply and persist both."""
        history = self.load_history()
        history.append({"role": "user", "content": user_message})
        messages = [{"role": "system", "content": _system_prompt(self.load_profile())}]
        messages.extend(history)
        answer = self._chat(messages)
        history.append({"role": "assistant", "content": answer})
        self.save_history(history)
        return answer

    def synthesize_profile(self) -> str:
        """Rebuild the Markdown profile from the current conversation."""
        history = self.load_history()
        conversation = json.dumps(history, ensure_ascii=False, indent=2)
        messages = [
            {"role": "system", "content": PROFILE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Conversazione:\n{conversation}"},
        ]
        profile = self._chat(messages)
        self.save_profile(profile)
        return profile

    def derive_profile_from_ledger(self, df, positions=None) -> tuple[str, dict]:
        """Infer/update the profile from ledger statistics.

        Sends a compact aggregate summary (plus representative trades) to the
        LLM, saves the resulting profile and returns ``(profile, summary)``.
        """
        summary = build_ledger_summary(df, positions)
        messages = [
            {"role": "system", "content": LEDGER_SYSTEM_PROMPT},
            {"role": "user", "content": format_ledger_summary(summary)},
        ]
        profile = self._chat(messages)
        self.save_profile(profile)
        return profile, summary


def get_trading_profile(base_dir: str = ".") -> str:
    """Reusable accessor: return the saved trading profile, or '' if none."""
    path = os.path.join(base_dir, PROFILE_FILENAME)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""
