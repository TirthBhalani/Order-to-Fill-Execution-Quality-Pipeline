# Data Source Map

![Source Map](file:///c:/Users/amitb/Desktop/Projects/FDE/Assignment-2/diagrams/source_map.png)

| Source Name | System / Vendor | Retrieval Mode | Data Format | Primary Keys / Grain | Known Gaps / Limitations | Owner |
|---|---|---|---|---|---|---|
| Market Prices | yfinance API | REST API / Python Lib | Dataframe / CSV | `(timestamp, symbol)` | 5-minute aggregation interval; missing market order book depth. | Market Data Team |
| Signal Log | Internal OMS / Algo Desk | Local CSV File | CSV | `signal_id` | Simulated data; generation model uses synthetic price offset. | Algo Trading Desk |
| Order / Fill Book | Broker Gateway Simulation | Local CSV File | CSV | `order_id` | Simulated broker feed; includes intentional latency/slippage noise & corrupt rows for DQ validation. | Brokerage Operations |
