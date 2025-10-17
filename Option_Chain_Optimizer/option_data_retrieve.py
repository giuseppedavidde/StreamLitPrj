from ib_insync import *

util.startLoop()

ib = IB()
ib.connect("127.0.0.1", 7497, clientId=12)

nvda = Stock("NVDA", "SMART", "USD")
ib.qualifyContracts(nvda)
ib.reqMarketDataType(3)  # Request delayed market data
[ticker] = ib.reqTickers(nvda)
nvdaValue = ticker.marketPrice()
print(f"NVDA delayed market price: {nvdaValue}")

chains = ib.reqSecDefOptParams(nvda.symbol, "", nvda.secType, nvda.conId)
chain = next(c for c in chains if c.tradingClass == "NVDA" and c.exchange == "SMART")

strikes = [
    strike
    for strike in chain.strikes
    if strike % 5 == 0 and nvdaValue - 20 < strike < nvdaValue + 20
]

expirations = sorted(exp for exp in chain.expirations)[:3]
rights = ["C", "P"]
print(f"Strikes: {strikes}")
print(f"Expirations: {expirations}")

contracts = [
    Option("NVDA", expiration, strike, right, "SMART", tradingClass="NVDA")
    for right in rights
    for expiration in expirations
    for strike in strikes
]

contracts = ib.qualifyContracts(*contracts)
tickers = ib.reqTickers(*contracts)

contractData = [
    (
        t.contract.lastTradeDateOrContractMonth,
        t.contract.strike,
        t.contract.right,
        t.time,
        t.close,
        nvdaValue,
    )
    for t in tickers
]

fields = [
    "expiration",
    "strike",
    "right",
    "time",
    "undPrice",
    "close",
]

print("Option Chain Data: {contractData}")
