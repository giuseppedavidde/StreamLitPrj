"""
IBKR Portfolio Analysis Dashboard
==================================
A Streamlit dashboard for analyzing Interactive Brokers portfolio data.
Displays portfolio composition, instrument breakdown, and market prices.
"""

from pathlib import Path
import warnings
import streamlit as st
import pandas as pd
import plotly.express as px


warnings.filterwarnings("ignore")

# ============================================================================
# PAGE CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="IBKR Portfolio Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

@st.cache_data
def load_portfolio_data(file_path):
    """Load and clean IBKR portfolio data."""
    try:
        # Read CSV with proper handling
        df = pd.read_csv(file_path)
        
        # Reset index to convert index values to a column
        df = df.reset_index()
        
        # Rename the 'index' column to 'Symbol' if it exists
        if 'index' in df.columns:
            df = df.rename(columns={'index': 'Symbol'})
        
        # If there's a duplicate 'Symbol' column, keep only the first one
        if df.columns.tolist().count('Symbol') > 1:
            # Get indices of all Symbol columns
            symbol_indices = [i for i, col in enumerate(df.columns) if col == 'Symbol']
            # Keep only the first Symbol column, drop the rest
            cols_to_drop = [df.columns[i] for i in symbol_indices[1:]]
            df = df.drop(columns=cols_to_drop)
        
        # Clean column names - strip whitespace
        df.columns = df.columns.str.strip()
        
        # Remove any completely empty columns (trailing commas in CSV)
        df = df.dropna(axis=1, how='all')
        
        # Convert numeric columns - handle special prefixes (C, M, -)
        for col in ['Bid', 'Ask', 'Last', 'Strike']:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str)
                    .str.strip()           # Remove leading/trailing whitespace
                    .str.replace('C', '')  # Remove C prefix (common in prices)
                    .str.replace('M', '-') # Replace M prefix with minus (for negative values)
                    .str.replace("'", '')  # Remove quotes
                    ,
                    errors='coerce'
                )
        
        # Handle expiry dates - replace 'null' strings with NaN
        if 'Expiry' in df.columns:
            df['Expiry'] = df['Expiry'].astype(str).str.strip()
            df['Expiry'] = df['Expiry'].where(df['Expiry'] != 'null', None)
            df['Expiry'] = pd.to_datetime(df['Expiry'], format='%Y%m%d', errors='coerce')
        
        # Fill null values for Strike
        if 'Strike' in df.columns:
            df['Strike'] = df['Strike'].fillna(0)
        
        # Create mid-price (average of Bid and Ask)
        if 'Bid' in df.columns and 'Ask' in df.columns:
            df['Mid_Price'] = (df['Bid'] + df['Ask']) / 2
            # Fallback to Last if Bid/Ask not available
            if 'Last' in df.columns:
                df['Mid_Price'] = df['Mid_Price'].fillna(df['Last'])
        
        return df
    except (FileNotFoundError, pd.errors.ParserError, ValueError) as e:
        st.error(f"Error loading data: {e}")
        return None


def get_portfolio_stats(df):
    """Calculate portfolio statistics."""
    stats = {
        'total_instruments': len(df),
        'instrument_types': df['Type'].unique().tolist(),
        'currencies': df['Currency'].unique().tolist(),
        'exchanges': df['Exchange'].unique().tolist(),
    }
    return stats


def categorize_instruments(df):
    """Categorize instruments by type."""
    categories = {
        'Stocks': df[df['Type'] == 'STK'],
        'Options': df[df['Type'] == 'OPT'],
        'Warrants': df[df['Type'] == 'WAR'],
        'Bags': df[df['Type'] == 'BAG'],
    }
    return {k: v for k, v in categories.items() if len(v) > 0}


# ============================================================================
# MAIN APP
# ============================================================================

def main():
    # Title
    st.title("📊 IBKR Portfolio Dashboard")
    st.markdown("Interactive analysis of Interactive Brokers portfolio data")
    
    # Load data - try multiple possible paths
    possible_paths = [
        Path(__file__).parent.parent.parent / "Data_for_Analysis" / "IBKR_Portfolio.csv",
        Path.cwd().parent.parent / "Data_for_Analysis" / "IBKR_Portfolio.csv",
        Path(__file__).parent / "Data_for_Analysis" / "IBKR_Portfolio.csv",
    ]
    
    file_path = None
    for path in possible_paths:
        if path.exists():
            file_path = path
            break
    
    if file_path is None:
        error_msg = f"""
        Portfolio file not found!
        
        Searched in:
        """
        for path in possible_paths:
            error_msg += f"\n  - {path}"
        st.error(error_msg)
        st.stop()
    
    df = load_portfolio_data(file_path)
    if df is None or df.empty:
        st.error("Failed to load portfolio data")
        st.stop()
    
    # Get statistics
    stats = get_portfolio_stats(df)
    instrument_categories = categorize_instruments(df)
    
    # ========================================================================
    # SIDEBAR FILTERS
    # ========================================================================
    with st.sidebar:
        st.header("Filters")
        
        # Filter by Type
        selected_types = st.multiselect(
            "Instrument Types",
            options=stats['instrument_types'],
            default=stats['instrument_types'],
            key="type_filter"
        )
        
        # Filter by Currency
        selected_currencies = st.multiselect(
            "Currencies",
            options=stats['currencies'],
            default=stats['currencies'],
            key="currency_filter"
        )
        
        # Apply filters
        filtered_df = df[
            (df['Type'].isin(selected_types)) & 
            (df['Currency'].isin(selected_currencies))
        ]
        
        st.markdown("---")
        st.metric("Filtered Instruments", len(filtered_df))
    
    # ========================================================================
    # TOP METRICS
    # ========================================================================
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Instruments", len(filtered_df))
    
    with col2:
        st.metric("Instrument Types", len(stats['instrument_types']))
    
    with col3:
        st.metric("Currencies", len(stats['currencies']))
    
    with col4:
        st.metric("Exchanges", len(stats['exchanges']))
    
    st.markdown("---")
    
    # ========================================================================
    # MAIN DASHBOARD TABS
    # ========================================================================
    tab1, tab2, tab3, tab4 = st.tabs([
        "📈 Overview",
        "🔍 Details",
        "💱 Pricing",
        "📋 Raw Data"
    ])
    
    # ========================================================================
    # TAB 1: OVERVIEW
    # ========================================================================
    with tab1:
        st.subheader("Portfolio Overview")
        
        col1, col2 = st.columns(2)
        
        # Instrument Type Distribution
        with col1:
            type_counts = filtered_df['Type'].value_counts()
            fig_type = px.pie(
                values=type_counts.values,
                names=type_counts.index,
                title="Instrument Type Distribution",
                hole=0.3
            )
            fig_type.update_layout(height=400)
            st.plotly_chart(fig_type, use_container_width=True)
        
        # Currency Distribution
        with col2:
            currency_counts = filtered_df['Currency'].value_counts()
            fig_currency = px.pie(
                values=currency_counts.values,
                names=currency_counts.index,
                title="Currency Distribution",
                hole=0.3
            )
            fig_currency.update_layout(height=400)
            st.plotly_chart(fig_currency, use_container_width=True)
        
        # Exchange Distribution
        st.subheader("Exchange Distribution")
        exchange_counts = filtered_df['Exchange'].value_counts()
        fig_exchange = px.bar(
            x=exchange_counts.index,
            y=exchange_counts.values,
            title="Instruments by Exchange",
            labels={'x': 'Exchange', 'y': 'Count'}
        )
        fig_exchange.update_layout(height=400)
        st.plotly_chart(fig_exchange, use_container_width=True)
    
    # ========================================================================
    # TAB 2: DETAILS BY CATEGORY
    # ========================================================================
    with tab2:
        st.subheader("Detailed Instrument Analysis")
        
        for category_name, category_df in instrument_categories.items():
            # Filter category by selected types and currencies
            category_df = category_df[
                (category_df['Type'].isin(selected_types)) & 
                (category_df['Currency'].isin(selected_currencies))
            ]
            
            if len(category_df) == 0:
                continue
            
            with st.expander(f"📍 {category_name} ({len(category_df)} items)", expanded=False):
                # Display table
                display_cols = ['Symbol', 'Type', 'Strike', 'P/C', 'Expiry', 'Currency', 'Bid', 'Ask', 'Last', 'Mid_Price']
                display_cols = [col for col in display_cols if col in category_df.columns]
                
                # Format dataframe for better display
                display_df = category_df[display_cols].reset_index(drop=True).copy()
                
                # Configure column display
                st.dataframe(
                    display_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        'Symbol': st.column_config.TextColumn(
                            'Symbol',
                            width='medium'
                        ),
                        'Type': st.column_config.TextColumn(
                            'Type',
                            width='small'
                        ),
                        'P/C': st.column_config.TextColumn(
                            'P/C',
                            width='small'
                        ),
                        'Strike': st.column_config.NumberColumn(
                            'Strike',
                            format='%.2f',
                            width='small'
                        ),
                        'Bid': st.column_config.NumberColumn(
                            'Bid',
                            format='%.2f',
                            width='small'
                        ),
                        'Ask': st.column_config.NumberColumn(
                            'Ask',
                            format='%.2f',
                            width='small'
                        ),
                        'Last': st.column_config.NumberColumn(
                            'Last',
                            format='%.2f',
                            width='small'
                        ),
                        'Mid_Price': st.column_config.NumberColumn(
                            'Mid_Price',
                            format='%.2f',
                            width='small'
                        ),
                    }
                )
                
                # Statistics for this category
                if len(category_df) > 0:
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        st.metric("Count", len(category_df))
                    
                    with col2:
                        avg_bid = category_df['Bid'].mean()
                        st.metric("Avg Bid", f"{avg_bid:.2f}" if pd.notna(avg_bid) else "N/A")
                    
                    with col3:
                        avg_ask = category_df['Ask'].mean()
                        st.metric("Avg Ask", f"{avg_ask:.2f}" if pd.notna(avg_ask) else "N/A")
                    
                    with col4:
                        avg_spread = ((category_df['Ask'] - category_df['Bid']) / category_df['Bid'] * 100).mean()
                        st.metric("Avg Spread %", f"{avg_spread:.2f}%" if pd.notna(avg_spread) else "N/A")
    
    # ========================================================================
    # TAB 3: PRICING ANALYSIS
    # ========================================================================
    with tab3:
        st.subheader("Pricing Analysis")
        
        col1, col2 = st.columns(2)
        
        # Bid-Ask Spread Analysis
        with col1:
            filtered_df['Spread'] = ((filtered_df['Ask'] - filtered_df['Bid']) / filtered_df['Bid'] * 100).fillna(0)
            
            fig_spread = px.box(
                filtered_df,
                y='Spread',
                title="Bid-Ask Spread Distribution (%)",
                points="all"
            )
            fig_spread.update_layout(height=400)
            st.plotly_chart(fig_spread, use_container_width=True)
        
        # Mid Price Distribution by Currency
        with col2:
            fig_price = px.box(
                filtered_df,
                x='Currency',
                y='Mid_Price',
                title="Mid Price Distribution by Currency",
                points="all"
            )
            fig_price.update_layout(height=400)
            st.plotly_chart(fig_price, use_container_width=True)
        
        # Bid-Ask Scatter
        st.subheader("Bid vs Ask Price Comparison")
        
        scatter_data = filtered_df.dropna(subset=['Bid', 'Ask'])  # type: ignore
        if len(scatter_data) > 0:
                fig_scatter = px.scatter(
                    scatter_data,
                    x='Bid',
                    y='Ask',
                    hover_data=['Type', 'Currency'],
                    title="Bid vs Ask Prices",
                    color='Currency'
                )
                fig_scatter.add_shape(
                    type="line",
                    x0=scatter_data['Bid'].min(),
                    y0=scatter_data['Bid'].min(),
                    x1=scatter_data['Bid'].max(),
                    y1=scatter_data['Bid'].max(),
                    line=dict(dash="dash", color="gray"),
                    name="Perfect Match"
                )
                st.plotly_chart(fig_scatter, use_container_width=True)
    
    # ========================================================================
    # TAB 4: RAW DATA
    # ========================================================================
    with tab4:
        st.subheader("Raw Portfolio Data")
        
        # Display full dataframe with column config
        st.dataframe(
            filtered_df.reset_index(drop=True),
            use_container_width=True,
            height=600,
            column_config={
                'Symbol': st.column_config.TextColumn(
                    'Symbol',
                    width='medium'
                ),
                'Type': st.column_config.TextColumn(
                    'Type',
                    width='small'
                ),
                'P/C': st.column_config.TextColumn(
                    'P/C',
                    width='small'
                ),
                'Strike': st.column_config.NumberColumn(
                    'Strike',
                    format='%.2f',
                    width='small'
                ),
                'Bid': st.column_config.NumberColumn(
                    'Bid',
                    format='%.2f',
                    width='small'
                ),
                'Ask': st.column_config.NumberColumn(
                    'Ask',
                    format='%.2f',
                    width='small'
                ),
                'Last': st.column_config.NumberColumn(
                    'Last',
                    format='%.2f',
                    width='small'
                ),
                'Mid_Price': st.column_config.NumberColumn(
                    'Mid_Price',
                    format='%.2f',
                    width='small'
                ),
            }
        )
        
        # Download button
        csv = filtered_df.to_csv(index=False)
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name="ibkr_portfolio_filtered.csv",
            mime="text/csv",
            key="download_csv"
        )


if __name__ == "__main__":
    main()
