# Quick Start Guide - IBKR Portfolio Dashboard

## Installation & Running

### Step 1: Install Dependencies
```powershell
cd StreamLitPrj\IBKR_Portfolio
pip install -r requirements.txt
```

### Step 2: Run the Dashboard
```powershell
streamlit run IBKR_Portfolio_Dashboard.py
```

The dashboard will automatically open in your browser at `http://localhost:8501`

## What You'll See

### 📈 Overview Tab
- Visual breakdown of your portfolio by instrument type, currency, and exchange
- Pie charts and bar charts for easy portfolio composition analysis

### 🔍 Details Tab
- Expandable sections for each instrument type (Stocks, Options, Warrants, Bags)
- Detailed pricing and statistical information
- Average bid, ask, and spread calculations per category

### 💱 Pricing Tab
- Bid-ask spread distribution across instruments
- Price range analysis by currency
- Scatter plot showing bid vs ask price correlation

### 📋 Raw Data Tab
- Full interactive table of all portfolio data
- Download filtered data as CSV

## Using the Filters

Use the sidebar to:
1. Select which **Instrument Types** to view (STK, OPT, WAR, BAG)
2. Select which **Currencies** to view (USD, EUR, etc.)

All charts and tables update automatically based on your selections!

## File Structure

```
StreamLitPrj/
└── IBKR_Portfolio/
    ├── IBKR_Portfolio_Dashboard.py      # Main app (run this!)
    ├── requirements.txt                 # Dependencies
    ├── README.md                        # Full documentation
    └── QUICKSTART.md                    # This file
```

## Troubleshooting

**Q: "ModuleNotFoundError: No module named 'streamlit'"**
- A: Run `pip install -r requirements.txt` first

**Q: CSV file not found error**
- A: Ensure `Data_for_Analysis/IBKR_Portfolio.csv` exists in the workspace root

**Q: Port 8501 already in use**
- A: Run `streamlit run IBKR_Portfolio_Dashboard.py --server.port 8502`

**Q: Nothing happens when I click filters**
- A: Wait a moment - Streamlit is recomputing. Check that you selected at least one option in both filters.

## Features at a Glance

✅ Real-time filtering by instrument type and currency  
✅ Interactive charts with Plotly  
✅ Portfolio statistics and metrics  
✅ Bid-ask spread analysis  
✅ CSV export functionality  
✅ Professional, responsive UI  
✅ Efficient data caching  

## Next Steps

1. ✅ Run the dashboard
2. ✅ Explore your portfolio data
3. ✅ Try different filters and visualizations
4. ✅ Export data for further analysis

Enjoy analyzing your IBKR portfolio! 📊
