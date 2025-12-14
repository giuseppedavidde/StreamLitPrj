# 📊 IBKR Portfolio Dashboard - Complete Package

## 🎯 Quick Links

| Document | Purpose |
|----------|---------|
| 🚀 [QUICKSTART.md](./QUICKSTART.md) | **Start here!** Fast setup in 3 steps |
| 📖 [README.md](./README.md) | Complete documentation & features |
| ✅ [SETUP_COMPLETE.md](./SETUP_COMPLETE.md) | What was created & next steps |
| ⚙️ [INDEX.md](./INDEX.md) | This file - file structure guide |

---

## 📁 Project Files

### 🔴 Main Application
```
IBKR_Portfolio_Dashboard.py  (342 lines)
```
The complete Streamlit dashboard application with:
- 📈 Overview tab with portfolio visualizations
- 🔍 Detailed category analysis
- 💱 Pricing analysis with bid-ask spreads
- 📋 Raw data table with CSV export
- 🎛️ Sidebar filters for real-time updates

### 📦 Dependencies
```
requirements.txt
```
Python packages needed:
- streamlit (1.28.0+) - Web framework
- pandas (2.0.0+) - Data analysis
- numpy (1.24.0+) - Numerical computing
- plotly (5.17.0+) - Interactive charts

### 📚 Documentation Files
```
README.md              - Full feature documentation
QUICKSTART.md          - 3-step quick start guide
SETUP_COMPLETE.md      - Setup recap & customization ideas
INDEX.md              - This file (file structure)
```

### 🚀 Launch Scripts
```
run_dashboard.bat     - Windows batch launcher
run_dashboard.ps1     - Windows PowerShell launcher
```

---

## 🔄 How to Use

### Option 1: PowerShell (Recommended)
```powershell
.\run_dashboard.ps1
```

### Option 2: Command Prompt
```cmd
run_dashboard.bat
```

### Option 3: Manual
```powershell
pip install -r requirements.txt
streamlit run IBKR_Portfolio_Dashboard.py
```

---

## 📊 Dashboard Overview

### 🎨 4 Main Tabs

#### 📈 Overview
- Instrument type distribution (pie chart)
- Currency distribution (pie chart)
- Exchange distribution (bar chart)
- Quick portfolio snapshot

#### 🔍 Details
- Stocks breakdown (expandable)
- Options breakdown (expandable)
- Warrants breakdown (expandable)
- Bags breakdown (expandable)
- Category statistics

#### 💱 Pricing
- Bid-ask spread distribution
- Price range by currency
- Bid vs ask correlation
- Advanced pricing metrics

#### 📋 Raw Data
- Full interactive table
- CSV export function
- Filter-respecting download

### 🎛️ Sidebar Filters
- **Instrument Types**: Select STK, OPT, WAR, BAG
- **Currencies**: Select USD, EUR, etc.
- Real-time chart updates

---

## 📈 Key Features

✅ **Interactive Charts**
- Pie charts, bar charts, box plots, scatter plots
- Hover details, zoom, pan capabilities
- Professional Plotly visualizations

✅ **Smart Filtering**
- Multi-select filters
- Real-time updates
- Filter status tracking

✅ **Data Analysis**
- Automatic statistics calculation
- Bid-ask spread analysis
- Currency breakdown

✅ **Data Export**
- CSV download button
- Respects current filters
- Easy external analysis

✅ **Professional UI**
- Wide responsive layout
- Dark/light theme support
- Organized tabs and sections

✅ **Performance**
- Data caching with @st.cache_data
- Fast filter updates
- Efficient pandas operations

---

## 🔧 Technical Stack

| Component | Technology | Version |
|-----------|------------|---------|
| Language | Python | 3.13.3 |
| Environment | Virtual Environment (.venv) | - |
| Web Framework | Streamlit | ≥1.28.0 |
| Data Processing | Pandas | ≥2.0.0 |
| Visualizations | Plotly | ≥5.17.0 |
| Numerical | NumPy | ≥1.24.0 |

---

## 📊 Data Source

**File**: `Data_for_Analysis/IBKR_Portfolio.csv`

**Columns**:
| Column | Type | Example |
|--------|------|---------|
| Symbol | string | GME, AAPL |
| Type | string | STK, OPT, WAR, BAG |
| Expiry | date | 202606 (null for stocks) |
| Strike | float | 87.5 |
| P/C | string | P (Put), C (Call) |
| Exchange | string | SMART |
| Currency | string | USD, EUR |
| Bid | float | 21.39 |
| Ask | float | 21.40 |
| Last | float | 21.41 |

---

## 🎯 Workflow

```
1. Run Dashboard
   ↓
2. Load CSV (cached)
   ↓
3. Clean & Process Data
   ↓
4. Select Filters (sidebar)
   ↓
5. View Visualizations (tabs)
   ↓
6. Export Data (if needed)
```

---

## 💡 Customization

### Change Port
```powershell
streamlit run IBKR_Portfolio_Dashboard.py --server.port 8502
```

### Add More Filters
Edit the sidebar filters section in `IBKR_Portfolio_Dashboard.py`

### Modify Visualizations
Edit the specific tab sections for chart changes

### Theme Customization
Add `.streamlit/config.toml` with theme settings

---

## ❓ Troubleshooting

| Issue | Solution |
|-------|----------|
| Port 8501 in use | Use `--server.port 8502` |
| CSV not found | Check `Data_for_Analysis/IBKR_Portfolio.csv` exists |
| Import errors | Run `pip install -r requirements.txt` |
| Slow performance | Clear cache: `streamlit cache clear` |
| No data displayed | Check filters - select at least one type/currency |

---

## 📁 Directory Structure

```
StreamLitPrj/
└── IBKR_Portfolio/
    ├── .venv/                          # Virtual environment
    ├── IBKR_Portfolio_Dashboard.py     # Main app (342 lines)
    ├── requirements.txt                # Dependencies
    ├── run_dashboard.bat               # Windows batch launcher
    ├── run_dashboard.ps1               # PowerShell launcher
    ├── README.md                       # Full documentation
    ├── QUICKSTART.md                   # Quick start guide
    ├── SETUP_COMPLETE.md              # Setup recap
    └── INDEX.md                        # This file
```

---

## 🎓 Next Steps

1. ✅ **Read** [QUICKSTART.md](./QUICKSTART.md)
2. ✅ **Run** `.\run_dashboard.ps1`
3. ✅ **Explore** the 4 tabs and filters
4. ✅ **Export** data as needed
5. ✅ **Customize** based on your needs

---

## 📧 Support

For issues or feature requests, refer to the main project:
- Repository: MyGITprj
- Owner: Giuseppe Davidde
- Branch: main

---

**Status**: ✅ Ready to Use  
**Created**: November 12, 2025  
**Environment**: Python 3.13.3 Virtual Environment  
**Dependencies**: Installed & Verified
