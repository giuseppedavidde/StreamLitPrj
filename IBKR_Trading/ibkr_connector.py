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

from ib_insync import IB, Stock, Option, util
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
