@echo off
REM IBKR Portfolio Dashboard - Launch Script for Windows
REM This script runs the Streamlit dashboard

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║  IBKR Portfolio Dashboard - Streamlit Application          ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

REM Check if Python virtual environment exists
if not exist ".venv" (
    echo ⚠️  Virtual environment not found!
    echo.
    echo Creating virtual environment...
    python -m venv .venv
    echo ✅ Virtual environment created
    echo.
    echo Installing dependencies...
    .\.venv\Scripts\pip install -q -r requirements.txt
    echo ✅ Dependencies installed
    echo.
)

REM Check if Streamlit is installed
.\.venv\Scripts\pip show streamlit >nul 2>&1
if %errorlevel% neq 0 (
    echo 📦 Installing dependencies...
    .\.venv\Scripts\pip install -r requirements.txt
    echo ✅ Dependencies installed
    echo.
)

echo 🚀 Starting IBKR Portfolio Dashboard...
echo.
echo 📊 Dashboard will open at: http://localhost:8501
echo 📝 Press Ctrl+C to stop the server
echo.

.\.venv\Scripts\streamlit run IBKR_Portfolio_Dashboard.py

pause
