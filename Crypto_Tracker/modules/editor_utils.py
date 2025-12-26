import pandas as pd
import io

def calculate_dca_update(df, asset_symbol, amount_invested, quantity, is_staking=False, update_date=None, buy_price=None):
    """
    Updates the portfolio DataFrame with a new buy transaction (DCA).
    
    Args:
        df (pd.DataFrame): Current portfolio DataFrame.
        asset_symbol (str): Symbol of the asset (e.g., 'BTC').
        amount_invested (float): Amount of fiat invested (EUR) or Value of Reward if Staking.
        quantity (float): Quantity of asset bought/sold.
        is_staking (bool): If True, amount_invested is treated as Reward Value (not fiat cost).
        update_date (str): Date of the transaction.
        buy_price (float): Optional. Implied price for reference.
        
    Returns:
        pd.DataFrame: Updated DataFrame.
    """
    # Ensure asset_symbol is uppercase
    asset_symbol = asset_symbol.upper().strip()
    

    # Use quantity directly
    new_shares = quantity
    
    # If staking, the actual fiat cost added to portfolio is 0 (it's a reward)
    fiat_cost_impact = 0.0 if is_staking else amount_invested
    
    
    # Check if asset exists
    # Ensure new columns exist
    if "date_last_update_buy" not in df.columns:
        df["date_last_update_buy"] = ""
    if "date_last_update_staking" not in df.columns:
        df["date_last_update_staking"] = ""

    if "asset_collect" in df.columns:
        # Filter for the asset
        mask = df["asset_collect"] == asset_symbol
        
        if mask.any():
            # Update existing
            idx = df[mask].index[0]
            
            current_shares = df.at[idx, "amount_asset_collect"]
            current_invested = df.at[idx, "amount_fiat_collect"]
            
            total_invested = current_invested + fiat_cost_impact
            total_shares = current_shares + new_shares
            
            # Weighted Average Price (DCA)
            new_average_price = total_invested / total_shares if total_shares > 0 and total_shares != 0 else 0
            
            if update_date:
                if is_staking:
                    df.at[idx, "date_last_update_staking"] = str(update_date)
                else:
                    df.at[idx, "date_last_update_buy"] = str(update_date)
            
            df.at[idx, "amount_asset_collect"] = total_shares
            df.at[idx, "amount_fiat_collect"] = total_invested
            df.at[idx, "median_price"] = new_average_price
            
        else:
            # Add new asset
            # Calculate implied price if not provided
            if buy_price is None:
                buy_price = amount_invested / quantity if quantity != 0 else 0
                
            new_row = {
                "asset_collect": asset_symbol,
                "Name": f"{asset_symbol} Crypto", # Default name if missing
                "amount_asset_collect": new_shares,
                "amount_fiat_collect": fiat_cost_impact,
                "median_price": buy_price if not is_staking else 0.0,
                "date_last_update_buy": str(update_date) if not is_staking and update_date else "",
                "date_last_update_staking": str(update_date) if is_staking and update_date else ""
            }
            # Append row
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            
    return df

def df_to_csv_content(df):
    """
    Converts the internal DataFrame back to the CSV format expected by the app/GitHub.
    Expected usage: Symbol;Name;Shares;Share Cost (EUR);Invested (EUR)
    Delimiter: ;
    """
    # Create a copy to map columns back
    export_df = df.copy()
    
    # Ensure correct columns exist (fill with defaults if missing)
    if "Name" not in export_df.columns:
        export_df["Name"] = export_df["asset_collect"] + " Crypto"
        
    # Map internal names to CSV headers
    # Internal: asset_collect, amount_asset_collect, amount_fiat_collect, median_price
    # CSV: Symbol, Shares, Invested (EUR), Share Cost (EUR)
    
    export_map = {
        "asset_collect": "Symbol",
        "amount_asset_collect": "Shares",
        "amount_fiat_collect": "Invested (EUR)",
        "median_price": "Share Cost (EUR)",
        "date_last_update_buy": "Last Update (Buy/Sell)",
        "date_last_update_staking": "Last Update (Staking)",
        "date_last_update": "Last Update" # Keep legacy if needed, but we prefer new ones
    }
    
    export_df = export_df.rename(columns=export_map)
    
    # Select only required columns in order, including Last Update
    columns_order = ["Symbol", "Name", "Shares", "Share Cost (EUR)", "Invested (EUR)", "Last Update (Buy/Sell)", "Last Update (Staking)"]
    
    # Keep only columns that exist
    final_cols = [c for c in columns_order if c in export_df.columns]
    
    out_buffer = io.StringIO()
    export_df[final_cols].to_csv(out_buffer, index=False, sep=";")
    
    return out_buffer.getvalue()
