# IBKR Portfolio Dashboard - Launch Script for PowerShell
# This script runs the Streamlit dashboard

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  IBKR Portfolio Dashboard - Streamlit Application          ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Check if Python virtual environment exists
if (-not (Test-Path ".venv")) {
    Write-Host "⚠️  Virtual environment not found!" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
    Write-Host "✅ Virtual environment created" -ForegroundColor Green
    Write-Host ""
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    & .\.venv\Scripts\pip install -q -r requirements.txt
    Write-Host "✅ Dependencies installed" -ForegroundColor Green
    Write-Host ""
}

# Check if Streamlit is installed
try {
    & .\.venv\Scripts\pip show streamlit > $null 2>&1
} catch {
    Write-Host "📦 Installing dependencies..." -ForegroundColor Yellow
    & .\.venv\Scripts\pip install -r requirements.txt
    Write-Host "✅ Dependencies installed" -ForegroundColor Green
    Write-Host ""
}

Write-Host "🚀 Starting IBKR Portfolio Dashboard..." -ForegroundColor Green
Write-Host ""
Write-Host "📊 Dashboard will open at: http://localhost:8501" -ForegroundColor Cyan
Write-Host "📝 Press Ctrl+C to stop the server" -ForegroundColor Cyan
Write-Host ""

& .\.venv\Scripts\streamlit run IBKR_Portfolio_Dashboard.py

Write-Host ""
Write-Host "Dashboard closed. Goodbye!" -ForegroundColor Gray
