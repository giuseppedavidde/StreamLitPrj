"""Dynamic ticker-based color theming for Streamlit."""

THEMES = [
    {'primary': '#0d6efd', 'secondary': '#6c757d', 'bg': '#f8f9fa'},  # Blue
    {'primary': '#198754', 'secondary': '#6c757d', 'bg': '#f8f9fa'},  # Green
    {'primary': '#dc3545', 'secondary': '#6c757d', 'bg': '#f8f9fa'},  # Red
    {'primary': '#fd7e14', 'secondary': '#6c757d', 'bg': '#f8f9fa'},  # Orange
    {'primary': '#6f42c1', 'secondary': '#6c757d', 'bg': '#f8f9fa'},  # Purple
    {'primary': '#20c997', 'secondary': '#6c757d', 'bg': '#f8f9fa'},  # Teal
    {'primary': '#e83e8c', 'secondary': '#6c757d', 'bg': '#f8f9fa'},  # Pink
    {'primary': '#ffc107', 'secondary': '#6c757d', 'bg': '#f8f9fa'},  # Yellow
]

SECTOR_THEMES = {
    'technology': 0,
    'healthcare': 3,
    'financial': 4,
    'energy': 2,
    'consumer': 5,
    'industrials': 1,
    'real estate': 6,
    'utilities': 7,
}


def get_theme(ticker: str) -> dict:
    """Deterministic theme for any ticker string."""
    idx = sum(ord(c) for c in ticker.upper()) % len(THEMES)
    return THEMES[idx]


def sector_theme(sector: str) -> dict:
    """Theme based on sector name."""
    key = sector.lower().strip() if sector else ''
    idx = SECTOR_THEMES.get(key, 0)
    return THEMES[idx]


def apply_theme(ticker: str):
    """Return CSS to inject into Streamlit for custom theming."""
    theme = get_theme(ticker)
    return f"""
    <style>
        .stApp {{ --primary-color: {theme['primary']}; }}
        .st-emotion-cache-1y4p8pa {{ color: {theme['primary']}; }}
        .st-emotion-cache-10trblm {{ color: {theme['primary']}; }}
    </style>
    """


VERDICT_COLORS = {
    'LONG-TERM INVESTMENT': '#198754',
    'SHORT-TERM SPECULATION': '#fd7e14',
    'AVOID': '#dc3545',
}

SCORE_COLORS = [
    (0, '#dc3545'),
    (40, '#fd7e14'),
    (60, '#ffc107'),
    (80, '#20c997'),
    (100, '#198754'),
]
