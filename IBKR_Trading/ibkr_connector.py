import asyncio
import logging

# Ensure an event loop exists BEFORE importing ib_insync.
# ib_insync's dependency (eventkit) calls get_event_loop() at module level.
# In Streamlit's ScriptRunner thread, no event loop exists by default.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import nest_asyncio

nest_asyncio.apply()

from ib_insync import (
    IB,
    Stock,
    Option,
    Contract,
    ComboLeg,
    LimitOrder,
    MarketOrder,
    util,
)
import pandas as pd


class _IBKRInfoFilter(logging.Filter):
    """Filter out purely informational IBKR error codes from ib_insync logs.

    Error 10091 = "Market data farm connection is OK" / delayed data notice.
    Error 10089 = "Not a valid firmquote" (informational).
    These are not failures; data still arrives correctly. Suppressing them
    avoids noise in the Streamlit terminal and application logs.
    """

    _SUPPRESSED = frozenset((10091, 10089))

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        msg = record.getMessage()
        for code in self._SUPPRESSED:
            if f"Error {code}," in msg or f"Error {code} " in msg:
                return False  # Drop this log record
        return True


# Apply filter to the ib_insync logger and its children
_ib_logger = logging.getLogger("ib_insync")
_ib_logger.addFilter(_IBKRInfoFilter())


class IBKRConnector:
    """Connector for Interactive Brokers via ib_insync.

    Handles the event-loop mismatch caused by Streamlit's ScriptRunner thread:
    after st.rerun(), the thread may have a NEW event loop, but the IB socket
    is still listening on the OLD one.  _ensure_loop() re-attaches the saved
    loop before every IB call so util.run() / loop.run_until_complete() work.
    """

    def __init__(self, request_timeout=30):
        self.ib = IB()
        self.ib.RequestTimeout = request_timeout
        self.connected = False
        # Save the event loop that IB will use for its socket I/O.
        # This is the loop active when the connector is created.
        self._loop = asyncio.get_event_loop()
        # Suppress noisy informational errors — Error 10091 is emitted by TWS
        # whenever delayed data is used instead of real-time. It's not a failure;
        # data still arrives correctly. We log it at DEBUG level only.
        self.ib.errorEvent += self._on_error  # type: ignore[operator]

    @staticmethod
    def _on_error(req_id: int, error_code: int, error_string: str, contract):
        """Centralized IBKR error handler. Demotes noisy informational codes."""
        if error_code in (10091, 10089, 399):
            # 10091 = delayed data availability notice (not a real error)
            # 10089 = not a firm quote (informational)
            # 399  = order message (informational)
            return  # Silently ignore — data still arrives correctly
        # For all other codes, print normally so real errors are visible
        print(
            f"[IBKR Error {error_code}] reqId={req_id}: "
            f"{error_string}" + (f" | Contract: {contract}" if contract else "")
        )

    def _patch_wrapper_error(self):
        """Monkey-patch ib_insync's internal EWrapper.error to suppress Error 10091/10089.

        ib_insync routes TWS error messages from the EClient socket directly to
        the wrapper's error() method, which then prints to stderr, bypassing the
        Python logging module entirely.  We wrap that method here to intercept and
        drop purely informational codes before they appear in the Streamlit log.
        """
        _SILENT = frozenset((10091, 10089))
        original_error = self.ib.wrapper.error  # type: ignore[attr-defined]

        def _filtered_error(req_id, error_code, error_string, contract=""):
            if error_code in _SILENT:
                return  # Drop silently — delayed data notice, not a real failure
            original_error(req_id, error_code, error_string, contract)

        self.ib.wrapper.error = _filtered_error  # type: ignore[method-assign]

    def _ensure_loop(self):
        """Re-attach the IB event loop to the current thread.

        Streamlit's ScriptRunner re-creates threads on st.rerun(), which may
        result in a different event loop being the 'current' one.  IB's socket
        traffic is still on self._loop, so we must make it current again.
        """
        try:
            current = asyncio.get_event_loop()
        except RuntimeError:
            current = None
        if current is not self._loop:
            asyncio.set_event_loop(self._loop)
            nest_asyncio.apply(self._loop)
            print(f"[IBKR] Re-attached event loop {id(self._loop):#x}")

    def connect(self, host="127.0.0.1", port=7496, clientId=1, timeout=15):
        """Connect to TWS or IB Gateway.

        If already connected, disconnect first to avoid stale state.
        """
        self._ensure_loop()

        # Always disconnect cleanly first to avoid Error 326 (clientId in use)
        if self.ib.isConnected():
            self.ib.disconnect()
            self.connected = False

        try:
            self.ib.connect(host, port, clientId=clientId, timeout=timeout)
            self.connected = True
            # After connecting, update the saved loop to the one IB is now using.
            self._loop = asyncio.get_event_loop()
            print(f"Connected to IBKR ({host}:{port})")
            # Patch the internal EWrapper.error to suppress Error 10091.
            # This error ("market data requires additional subscription") is purely
            # informational — TWS still delivers delayed data. Without this patch
            # ib_insync prints the raw error string directly via its EClient loop,
            # bypassing Python logging entirely.
            self._patch_wrapper_error()
        except TimeoutError:
            self.connected = False
            raise ConnectionError(
                f"Connection timed out after {timeout}s. "
                "Check that TWS/Gateway is running and API is enabled."
            )
        except ConnectionRefusedError:
            self.connected = False
            raise ConnectionError(
                f"Connection refused at {host}:{port}. "
                "Check that TWS/Gateway is running."
            )
        except Exception as e:
            self.connected = False
            raise ConnectionError(f"Connection failed: {e}")

    def disconnect(self):
        """Disconnect cleanly. Safe to call multiple times."""
        if self.ib.isConnected():
            self.ib.disconnect()
        self.connected = False

    def is_ready(self):
        """Check if connection is alive and sync our state flag.

        Also re-attaches the event loop so subsequent calls work.
        """
        self._ensure_loop()
        alive = self.ib.isConnected()
        if not alive:
            self.connected = False
        return alive

    def get_option_chain(self, ticker, progress_callback=None):
        """Get all available expirations and strikes for a ticker.

        Args:
            ticker: Stock symbol (e.g. 'AAPL').
            progress_callback: Optional callable(str) for progress updates.

        Returns:
            Tuple of (sorted_expirations, sorted_strikes).
        """
        if not self.is_ready():
            raise ConnectionError("Not connected to IBKR.")

        def _p(msg):
            if progress_callback:
                progress_callback(msg)

        # 1. Qualify the stock contract
        _p(f"📡 Qualifying {ticker}...")
        stock = Stock(ticker, "SMART", "USD")
        qualified = self.ib.qualifyContracts(stock)
        if not qualified:
            raise ValueError(f"Could not qualify stock: {ticker}")
        _p(f"✅ Qualified: conId={stock.conId}")

        # 2. Request option chain definitions
        _p("📥 Requesting option chain from IBKR...")
        chains = self.ib.reqSecDefOptParams(
            stock.symbol, "", stock.secType, stock.conId
        )
        if not chains:
            raise ValueError(f"No option chains found for {ticker}")

        # 3. Aggregate expirations & strikes across all exchanges
        all_exps = set()
        all_strikes = set()
        exchanges = []
        for chain in chains:
            exchanges.append(chain.exchange)
            all_exps.update(chain.expirations)
            all_strikes.update(chain.strikes)

        _p(
            f"✅ {len(all_exps)} expirations, {len(all_strikes)} strikes "
            f"on {', '.join(exchanges)}"
        )
        return sorted(all_exps), sorted(all_strikes)

    def get_strikes_for_expiration(self, ticker, expiry, currency="USD"):
        """Get the specific strikes available for a given expiration date.

        This prevents passing incorrect half-point strikes (from weeklies)
        to LEAPS which only have whole number strikes.
        """
        if not self.is_ready():
            raise ConnectionError("Not connected to IBKR.")

        self._ensure_loop()

        # We use an empty strike and an empty right to fetch all options for this expiry
        contract = Option(ticker, expiry, exchange="SMART", currency=currency)
        try:
            details = self.ib.reqContractDetails(contract)
            if not details:
                return []

            # Extract just the strikes and return a sorted unique list
            strikes = sorted(list(set(d.contract.strike for d in details)))
            return strikes
        except Exception as e:
            print(
                f"[ERROR] Failed to fetch specific strikes for {ticker} {expiry}: {e}"
            )
            return []

    def get_historical_data(
        self,
        ticker,
        sec_type="STK",
        exchange="SMART",
        currency="USD",
        duration="1 D",
        bar_size_setting="1 hour",
        what_to_show="TRADES",
        use_rth=True,
        **kwargs,
    ):
        """Retrieve historical bar data.

        For options, pass expiry, strike, right via kwargs.
        """
        if not self.is_ready():
            raise ConnectionError("Not connected to IBKR.")

        if sec_type == "STK":
            contract = Stock(ticker, exchange, currency)
            qualified = self.ib.qualifyContracts(contract)
            if not qualified:
                raise ValueError(
                    f"Could not qualify stock: {ticker}. Check the symbol."
                )
            contract = qualified[0]
        elif sec_type == "OPT":
            right = kwargs.get("right")
            expiry = kwargs.get("expiry")
            strike = kwargs.get("strike")
            if not (right and expiry and strike):
                raise ValueError("Options require 'right', 'expiry', and 'strike'.")

            contract = Option(
                ticker, expiry, float(strike), right, exchange, currency=currency
            )
            qualified = self.ib.qualifyContracts(contract)
            if not qualified:
                raise ValueError(
                    f"Could not qualify option: {ticker} {expiry} {strike} {right}"
                )
            contract = qualified[0]

            # Options often lack TRADES data; default to MIDPOINT
            if what_to_show == "TRADES":
                what_to_show = "MIDPOINT"
        else:
            raise ValueError(f"Unsupported security type: {sec_type}")

        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size_setting,
            whatToShow=what_to_show,
            useRTH=use_rth,
            formatDate=1,
        )

        df = util.df(bars)
        if df is not None and not df.empty:
            df.set_index("date", inplace=True)
        return df

    def get_implied_volatility(
        self,
        ticker,
        exchange="SMART",
        currency="USD",
        expiry=None,
        strike=None,
        right="C",
    ):
        """Get the Implied Volatility for a stock or a specific option.
        If expiry and strike are provided, fetches the exact IV from the option's modelGreeks (delay-friendly).
        Otherwise fetches the 30-day index IV (OPTION_IMPLIED_VOLATILITY) for the stock.
        Returns the IV value as a decimal (e.g. 1.06 for 106%), or None if unavailable.
        """
        if not self.is_ready():
            return None

        if expiry and strike:
            try:
                # Options are best qualified with an empty exchange "" rather than "SMART" to avoid Error 200
                contract = Option(
                    ticker, expiry, float(strike), right, "SMART", "", currency
                )
                qualified = self.ib.qualifyContracts(contract)

                # If it fails, try the opposite right just strictly to get the IV of the strike
                if not qualified:
                    alt_right = "P" if right == "C" else "C"
                    alt_contract = Option(
                        ticker,
                        expiry,
                        float(strike),
                        alt_right,
                        "SMART",
                        "",
                        currency,
                    )
                    qualified = self.ib.qualifyContracts(alt_contract)

                # If it still fails, try strict integer strike if it's a whole number
                if not qualified and float(strike).is_integer():
                    int_strike = int(float(strike))
                    int_contract = Option(
                        ticker,
                        expiry,
                        int_strike,
                        right,
                        "SMART",
                        "",
                        currency,
                    )
                    qualified = self.ib.qualifyContracts(int_contract)

                if qualified:
                    contract = qualified[0]
                    self.ib.reqMarketDataType(3)

                    # Request tick data for implied volatility (106)
                    ticker_data = self.ib.reqMktData(
                        contract, "106", snapshot=False, regulatorySnapshot=False
                    )

                    # Clear stale cached values to force waiting for fresh data
                    ticker_data.impliedVolatility = float("nan")

                    for _ in range(30):
                        self.ib.sleep(0.1)
                        iv = ticker_data.impliedVolatility
                        if iv == iv and iv != 0.0:
                            self.ib.cancelMktData(contract)
                            print(
                                f"📊 Native IBKR Option IV fetched for {expiry} {strike}{right}: {iv}"
                            )
                            return {"iv": float(iv), "hv": None, "avg": float(iv)}

                    self.ib.cancelMktData(contract)
            except Exception as e:
                print(
                    f"Failed to fetch option specific IV for {ticker} {expiry} {strike}: {e}"
                )

        # Fallback to Stock 30-day IV index (Average of Tick type 104 and 106)
        try:
            contract = Stock(ticker, exchange, currency)
            qualified = self.ib.qualifyContracts(contract)
            if qualified:
                contract = qualified[0]
                self.ib.reqMarketDataType(3)

                # Request tick data including implied volatility (106) and historical volatility (104)
                # TWS typically displays the average of these two for its main IV figure
                ticker_data = self.ib.reqMktData(
                    contract, "104,106", snapshot=False, regulatorySnapshot=False
                )

                # Clear stale cached values to force waiting for fresh data
                ticker_data.impliedVolatility = float("nan")
                ticker_data.histVolatility = float("nan")

                # Wait up to 3 seconds for volatilities to populate
                for _ in range(30):
                    self.ib.sleep(0.1)
                    iv = ticker_data.impliedVolatility
                    hv = ticker_data.histVolatility

                    iv_valid = iv == iv and iv != 0.0
                    hv_valid = hv == hv and hv != 0.0

                    if iv_valid and hv_valid:
                        self.ib.cancelMktData(contract)
                        avg_iv = float((iv + hv) / 2.0)
                        print(f"📊 Native IBKR IV fetched (106): {iv}")
                        print(f"📈 Native IBKR HV fetched (104): {hv}")
                        print(f"⚖️ Calculated Average: {avg_iv}")
                        return {"iv": float(iv), "hv": float(hv), "avg": avg_iv}

                # If we exhausted the loop, use whatever is available
                iv = ticker_data.impliedVolatility
                hv = ticker_data.histVolatility
                iv_valid = iv == iv and iv != 0.0
                hv_valid = hv == hv and hv != 0.0

                self.ib.cancelMktData(contract)

                if iv_valid and hv_valid:
                    avg_iv = float((iv + hv) / 2.0)
                    print(f"📊 Native IBKR IV fetched (106): {iv}")
                    print(f"📈 Native IBKR HV fetched (104): {hv}")
                    print(f"⚖️ Calculated Average: {avg_iv}")
                    return {"iv": float(iv), "hv": float(hv), "avg": avg_iv}
                elif iv_valid:
                    print(f"📊 Native IBKR IV fetched (106): {iv}")
                    return {"iv": float(iv), "hv": None, "avg": float(iv)}
                elif hv_valid:
                    print(f"📈 Native IBKR HV fetched (104): {hv}")
                    return {"iv": None, "hv": float(hv), "avg": float(hv)}

        except Exception as e:
            print(f"Failed to fetch stock live implied volatility for {ticker}: {e}")

        # Final Fallback to Historical 30-day IV index
        try:
            # We request 1 day of historical data using whatToShow='OPTION_IMPLIED_VOLATILITY'
            df = self.get_historical_data(
                ticker,
                sec_type="STK",
                exchange=exchange,
                currency=currency,
                duration="1 D",
                bar_size_setting="1 day",
                what_to_show="OPTION_IMPLIED_VOLATILITY",
            )
            if df is not None and not df.empty and "close" in df.columns:
                iv_close = float(df["close"].iloc[-1])
                print(f"📊 Native IBKR Historical IV fetched: {iv_close}")
                return {"iv": iv_close, "hv": None, "avg": iv_close}
        except Exception as e:
            print(
                f"Failed to fetch stock historical implied volatility for {ticker}: {e}"
            )
        return {"iv": None, "hv": None, "avg": None}

    def submit_strategy_order(
        self, ticker, legs, order_type="LMT", limit_price=None, total_quantity=1
    ):
        """Build and submit an option strategy order (single or combo).

        Args:
            ticker: The underlying symbol (e.g. 'AAPL')
            legs: List of dictionaries defining the strategy legs.
                  Each dict must have: action ('BUY' or 'SELL'), quantity (int),
                  expiry ('YYYYMMDD'), strike (float/str), right ('C' or 'P').
            order_type: "LMT" or "MKT". Defaults to "LMT".
            limit_price: Required if order_type is "LMT". The total limit price for the strategy.
            total_quantity: Number of times to execute the whole strategy. Defaults to 1.

        Returns:
            dict: Contains 'status' (success/error), 'msg' (details), and 'order_id' if successful.
        """
        if not self.is_ready():
            return {"status": "error", "msg": "Not connected to IBKR."}

        self._ensure_loop()

        if not legs:
            return {"status": "error", "msg": "No legs provided for the strategy."}

        try:
            # 1. Qualify all individual option contracts to get their conIds
            qualified_legs = []
            for leg in legs:
                opt = Option(
                    ticker,
                    leg["expiry"],
                    float(leg["strike"]),
                    leg["right"],
                    "SMART",
                    "",
                    "USD",
                )
                qualified = self.ib.qualifyContracts(opt)

                # If it fails, try the opposite right (not strictly needed for orders, but useful to catch weird data issues)
                if not qualified:
                    alt_right = "P" if leg["right"] == "C" else "C"
                    alt_contract = Option(
                        ticker,
                        leg["expiry"],
                        float(leg["strike"]),
                        alt_right,
                        "SMART",
                        "",
                        "USD",
                    )
                    qualified = self.ib.qualifyContracts(alt_contract)
                    if qualified:
                        # If the alternate right qualified, it means the LLM guessed the WRONG right for that strike (e.g. only puts exist)
                        # We must update the leg action to match reality, otherwise the order will fail
                        leg["right"] = alt_right
                        print(
                            f"⚠️ Corrected leg right to {alt_right} to match available IBKR chain."
                        )

                # If it still fails, try strict integer strike if it's a whole number
                if not qualified and float(leg["strike"]).is_integer():
                    int_strike = int(float(leg["strike"]))
                    int_contract = Option(
                        ticker,
                        leg["expiry"],
                        int_strike,
                        leg["right"],
                        "SMART",
                        "",
                        "USD",
                    )
                    qualified = self.ib.qualifyContracts(int_contract)

                if not qualified:
                    return {"status": "error", "msg": f"Could not qualify leg: {opt}"}

                # Store the qualified contract alongside the requested action/qty
                qualified_legs.append(
                    {
                        "contract": qualified[0],
                        "action": leg["action"],
                        "quantity": leg.get("quantity", 1),
                    }
                )

            # 2. Build the contract (Single Option vs BAG/Combo)
            if len(qualified_legs) == 1:
                # Single leg order
                main_contract = qualified_legs[0]["contract"]
                ib_action = qualified_legs[0]["action"]
                quantity = int(qualified_legs[0]["quantity"]) * total_quantity
            else:
                # Multi-leg Combo order (BAG)
                main_contract = Contract(
                    symbol=ticker, secType="BAG", exchange="SMART", currency="USD"
                )

                combo_legs = []
                for leg_info in qualified_legs:
                    conId = leg_info["contract"].conId
                    # For combo legs, action is relative to the combo order action.
                    # It's generally simpler to just set the combo order action to "BUY"
                    # and set the leg actions explicitly to what they should be.
                    leg_action = leg_info["action"]
                    combo_leg = ComboLeg(
                        conId=conId,
                        ratio=int(leg_info["quantity"]),
                        action=leg_action,
                        exchange="SMART",
                    )
                    combo_legs.append(combo_leg)

                main_contract.comboLegs = combo_legs
                ib_action = (
                    "BUY"  # The BAG is "bought", leg actions determine the actual trade
                )
                quantity = total_quantity

            # 3. Create the Order object
            if order_type.upper() == "MKT":
                order = MarketOrder(ib_action, quantity)
            elif order_type.upper() == "LMT":
                if limit_price is None:
                    return {
                        "status": "error",
                        "msg": "Limit price is required for LMT orders.",
                    }
                order = LimitOrder(ib_action, quantity, float(limit_price))
            else:
                return {
                    "status": "error",
                    "msg": f"Unsupported order type: {order_type}",
                }

            # 4. Submit the Order
            print(f"Submitting {order_type} order for {main_contract}: {order}")
            trade = self.ib.placeOrder(main_contract, order)

            # Wait briefly to let the order status update if possible
            for _ in range(5):
                self.ib.sleep(0.1)

            status = trade.orderStatus.status
            if status == "Cancelled" or status == "Inactive":
                msg = "Order cancelled or inactive. Check TWS for margin/data requirements."
                # Sometimes margin violations are reported in log
                if trade.log:
                    errors = [log.message for log in trade.log if log.message]
                    if errors:
                        msg += f" Details: {' | '.join(errors)}"
                return {"status": "error", "msg": msg}

            return {
                "status": "success",
                "msg": f"Order submitted successfully (Status: {status})",
                "order_id": order.orderId,
                "trade": trade,  # Passing back the trade object
            }

        except Exception as e:
            msg = f"Failed to submit strategy order: {e}"
            print(f"❌ {msg}")
            return {"status": "error", "msg": msg}

    def get_real_greeks_table(
        self, ticker, expiry_str, strikes, underlying_price, hist_vol, rate=0.05
    ):
        """
        Fetch real Bid/Ask mid-point prices for each option strike from IBKR.
        Uses ONLY tick type '100' (Bid/Ask delayed) which works WITHOUT a premium
        market data subscription, unlike modelGreeks which requires one.
        Local Black-Scholes Greeks (delta, gamma, theta, vega) are always used
        since they are computed independently from the real price.
        Falls back to theoretical Black-Scholes price if Bid/Ask is unavailable.
        """
        from option_utils import black_scholes_greeks, days_to_expiry
        import math

        dte = days_to_expiry(expiry_str)

        # Build pure-theoretical table first as the safe baseline
        bs_table = {}
        for s in strikes:
            bs_table[s] = {
                "C": black_scholes_greeks(
                    underlying_price, s, dte, rate, hist_vol, "C"
                ),
                "P": black_scholes_greeks(
                    underlying_price, s, dte, rate, hist_vol, "P"
                ),
            }

        if not self.is_ready() or not strikes:
            results = []
            for s in strikes:
                results.append(
                    {
                        "strike": s,
                        "expiry": expiry_str,
                        "dte": dte,
                        "call": bs_table[s]["C"],
                        "put": bs_table[s]["P"],
                    }
                )
            return results

        self._ensure_loop()

        # Set delayed market data (type 3) to avoid real-time subscription requirement
        self.ib.reqMarketDataType(3)

        # Build and qualify contracts one at a time to handle individual failures gracefully
        real_prices = {}  # {(strike, right): mid_price}

        # --- EARLY EXIT MECHANISM FOR ERROR 10167 (No Market Data) ---
        # If the user has no live data subscription for options, TWS will throw Error 10167.
        # Instead of waiting 20s x (number of strikes) and freezing the UI, we intercept
        # the error once and break out immediately to use theoretical Greeks.
        self._no_mkt_data = False
        original_error_handler = self.ib.wrapper.error  # type: ignore[attr-defined]

        def _catch_10167(req_id, error_code, error_string, contract=""):
            if error_code == 10167:
                self._no_mkt_data = True
                print(
                    f"⚠️ [Fast Fallback] Nessun abbonamento dati (Err 10167) rilevato. Interrompo le chiamate API per le opzioni."
                )
            # Still call the original to preserve the standard logging behavior
            original_error_handler(req_id, error_code, error_string, contract)

        self.ib.wrapper.error = _catch_10167  # type: ignore[method-assign]
        # -------------------------------------------------------------

        for s in strikes:
            if self._no_mkt_data:
                break  # Stop pinging IBKR entirely for this chain

            for right in ("C", "P"):
                if self._no_mkt_data:
                    break
                try:
                    contract = Option(
                        ticker, expiry_str, float(s), right, "SMART", "", "USD"
                    )
                    qualified = self.ib.qualifyContracts(contract)
                    if not qualified:
                        print(
                            f"[WARN] Could not qualify {ticker} {expiry_str} {s}{right}"
                        )
                        continue

                    qc = qualified[0]

                    # Request snapshot WITHOUT generic ticks — Bid/Ask arrive by default
                    # Using "100" (generic tick) with snapshot=True on delayed option data
                    # triggers Error 321 ("Invalid tick type for snapshot") on some contracts.
                    td = self.ib.reqMktData(
                        qc, "", snapshot=True, regulatorySnapshot=False
                    )

                    # Wait up to 2 seconds for Bid/Ask to populate
                    for _ in range(20):
                        self.ib.sleep(0.1)
                        bid = td.bid
                        ask = td.ask
                        bid_valid = bid is not None and bid == bid and bid > 0
                        ask_valid = ask is not None and ask == ask and ask > 0
                        if bid_valid and ask_valid:
                            real_prices[(float(s), right)] = round((bid + ask) / 2.0, 4)
                            break

                    self.ib.cancelMktData(qc)

                except Exception as e:
                    print(
                        f"[WARN] Bid/Ask fetch failed for {ticker} {expiry_str} {s}{right}: {e}"
                    )

        # Restore the original error handler so we don't accidentally leak state
        self.ib.wrapper.error = original_error_handler  # type: ignore[method-assign]

        # Compose results: real Bid/Ask mid-price + local Black-Scholes Greeks
        results = []
        for s in strikes:
            call_dict = bs_table[s]["C"].copy()
            put_dict = bs_table[s]["P"].copy()

            mid_call = real_prices.get((float(s), "C"))
            mid_put = real_prices.get((float(s), "P"))

            if mid_call is not None:
                call_dict["price"] = mid_call
                print(
                    f"✅ Real Bid/Ask price for {ticker} {expiry_str} {s}C: ${mid_call}"
                )

            if mid_put is not None:
                put_dict["price"] = mid_put
                print(
                    f"✅ Real Bid/Ask price for {ticker} {expiry_str} {s}P: ${mid_put}"
                )

            results.append(
                {
                    "strike": s,
                    "expiry": expiry_str,
                    "dte": dte,
                    "call": call_dict,
                    "put": put_dict,
                }
            )

        return results


if __name__ == "__main__":
    connector = IBKRConnector()
    try:
        connector.connect()
        df = connector.get_historical_data(
            "AAPL", duration="1 D", bar_size_setting="1 hour"
        )
        print(df.head())
    except Exception as e:
        print(f"Test failed: {e}")
    finally:
        connector.disconnect()
