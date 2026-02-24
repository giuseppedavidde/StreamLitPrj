import asyncio

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
