# IBKR Portfolio Dashboard

A comprehensive Streamlit dashboard for analyzing Interactive Brokers (IBKR) portfolio data. This application provides interactive visualizations and detailed analytics of your portfolio composition, pricing data, and instrument breakdown.

## Features

### 📈 Overview Tab
- **Instrument Type Distribution**: Pie chart showing the breakdown of stocks, options, warrants, and bags
- **Currency Distribution**: Pie chart visualizing portfolio currency exposure
- **Exchange Distribution**: Bar chart showing instruments by exchange

### 🔍 Details Tab
- **Category Breakdown**: Expandable sections for each instrument type
- **Detailed Tables**: View complete information for each category
- **Category Statistics**: Average bid, ask, and spread calculations per instrument type

### 💱 Pricing Tab
- **Bid-Ask Spread Analysis**: Distribution of spreads across all instruments
- **Price Distribution by Currency**: Box plots showing price ranges by currency
- **Bid vs Ask Scatter Plot**: Visualization of price correlation with instrument details

### 📋 Raw Data Tab
- **Full Dataset View**: Interactive table with all portfolio data
- **CSV Download**: Export filtered data for external analysis

## Setup

### Prerequisites
- Python 3.8+
- pip

### Installation

1. **Clone or navigate to the project directory:**
   ```bash
   cd StreamLitPrj/IBKR_Portfolio
   ```

2. **Create a virtual environment (optional but recommended):**
   ```bash
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1  # On Windows PowerShell
   source .venv/bin/activate      # On macOS/Linux
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Running the Dashboard

```bash
streamlit run IBKR_Portfolio_Dashboard.py
```

The dashboard will open in your default web browser at `http://localhost:8501`

### Data File Location

The application expects the portfolio data at:
```
Data_for_Analysis/IBKR_Portfolio.csv
```

### Sidebar Filters

- **Instrument Types**: Filter by STK, OPT, WAR, BAG
- **Currencies**: Filter by USD, EUR, etc.

The filtered data updates all visualizations in real-time.

## CSV Format

The `IBKR_Portfolio.csv` file should have the following columns:

| Column   | Type     | Description                          |
|----------|----------|--------------------------------------|
| Symbol   | string   | Trading symbol/ticker                |
| Type     | string   | Instrument type (STK, OPT, WAR, BAG) |
| Expiry   | date     | Expiration date (null for stocks)     |
| Strike   | float    | Strike price (for options)           |
| P/C      | string   | Put/Call indicator                   |
| Exchange | string   | Trading exchange (e.g., SMART)       |
| Currency | string   | Currency (USD, EUR, etc.)            |
| Bid      | float    | Current bid price                    |
| Ask      | float    | Current ask price                    |
| Last     | float    | Last traded price                    |

## Key Calculations

- **Mid Price**: Average of Bid and Ask prices (falls back to Last if unavailable)
- **Bid-Ask Spread %**: `(Ask - Bid) / Bid * 100`
- **Average Statistics**: Calculated per instrument category

## Project Structure

```
IBKR_Portfolio/
├── IBKR_Portfolio_Dashboard.py    # Main dashboard application
├── requirements.txt               # Python dependencies
└── README.md                      # This file
```

## Dependencies

- **streamlit**: Web application framework
- **pandas**: Data manipulation and analysis
- **plotly**: Interactive visualizations
- **numpy**: Numerical computations

## Features in Detail

### Data Cleaning
- Handles null values and "null" strings
- Converts dates to proper datetime format
- Parses price data with special characters (C, M prefixes)
- Calculates derived metrics (mid-price, spread)

### Performance
- Data caching with `@st.cache_data` for faster reloads
- Efficient filtering and grouping operations
- Optimized dataframe operations

### User Experience
- Responsive multi-tab interface
- Real-time filter updates
- Export functionality for data analysis
- Professional styling and layout

## Troubleshooting

### Port Already in Use
If port 8501 is already in use:
```bash
streamlit run IBKR_Portfolio_Dashboard.py --server.port 8502
```

### CSV File Not Found
Ensure the `Data_for_Analysis/IBKR_Portfolio.csv` file exists relative to the workspace root.

### Import Errors
Reinstall dependencies:
```bash
pip install --upgrade -r requirements.txt
```

## Future Enhancements

- Portfolio performance tracking over time
- Greeks calculation for options
- Risk metrics (VaR, Sharpe ratio)
- Historical data integration with yfinance
- Export to Excel with formatting
- Dark mode theme

## License

This project is part of MyGITprj by Giuseppe Davidde

## Support

For issues or feature requests, please refer to the main project repository.
