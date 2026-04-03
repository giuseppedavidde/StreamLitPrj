import pandas as pd
import yfinance as yf
from pycoingecko import CoinGeckoAPI

def compute_rsi(data, periods=14):
    """Calcola il Relative Strength Index (RSI)."""
    close_delta = data['Close'].diff()
    up = close_delta.clip(lower=0)
    down = -1 * close_delta.clip(upper=0)
    ma_up = up.ewm(com=periods - 1, adjust=True, min_periods=periods).mean()
    ma_down = down.ewm(com=periods - 1, adjust=True, min_periods=periods).mean()
    rsi = ma_up / ma_down
    rsi = 100 - (100 / (1 + rsi))
    return rsi

def get_dca_multiplier(symbol, current_price, rsi_w, ema20_w, wma200_w, mayer_d, dca_params=None):
    """Calcola il moltiplicatore Smart DCA (Dynamic Cost Averaging) usando parametri configurabili."""
    if dca_params is None:
        dca_params = {}
        
    multiplier = 1.0
    signals = []
    
    is_blue_chip = "BTC" in symbol.upper() or "ETH" in symbol.upper()
    def is_valid(val): return val != "N/A" and pd.notna(val)
    
    if is_blue_chip:
        btc_wma_prox = dca_params.get("btc_wma_prox", 1.05)
        btc_mayer_low = dca_params.get("btc_mayer_low", 0.8)
        btc_mayer_high = dca_params.get("btc_mayer_high", 2.4)
        btc_rsi_low = dca_params.get("btc_rsi_low", 40)
        btc_rsi_high = dca_params.get("btc_rsi_high", 75)
        
        if is_valid(wma200_w) and current_price <= wma200_w * btc_wma_prox:
            multiplier += 1.0
            signals.append("Vicino/Sotto 200WMA")
            
        if is_valid(mayer_d):
            if mayer_d < btc_mayer_low:
                multiplier += 1.0
                signals.append(f"Mayer < {btc_mayer_low} ({round(mayer_d,2)})")
            elif mayer_d > btc_mayer_high:
                multiplier -= 1.0
                signals.append(f"Mayer > {btc_mayer_high} ({round(mayer_d,2)}) - Rischio Bolla")
                
        if is_valid(rsi_w):
            if rsi_w < btc_rsi_low:
                multiplier += 0.5
                signals.append(f"Weekly RSI Sottovalutato ({round(rsi_w,1)})")
            elif rsi_w > btc_rsi_high:
                multiplier -= 0.5
                signals.append(f"Weekly RSI Ipercomprato ({round(rsi_w,1)})")
    else:
        # LOGICA ALTCOIN HIGH BETA
        alt_rsi_ext = dca_params.get("alt_rsi_ext", 30)
        alt_rsi_low = dca_params.get("alt_rsi_low", 40)
        alt_rsi_high = dca_params.get("alt_rsi_high", 70)
        alt_mayer_low = dca_params.get("alt_mayer_low", 0.8)
        alt_mayer_high = dca_params.get("alt_mayer_high", 2.0)
        
        if is_valid(rsi_w):
            if rsi_w < alt_rsi_ext:
                multiplier += 1.0
                signals.append(f"Weekly RSI Estremo Ipervenduto ({round(rsi_w,1)})")
            elif rsi_w < alt_rsi_low:
                multiplier += 0.5
                signals.append(f"Weekly RSI Sottovalutato ({round(rsi_w,1)})")
            elif rsi_w > alt_rsi_high:
                multiplier -= 1.0
                signals.append(f"Weekly RSI Ipercomprato ({round(rsi_w,1)})")
                
        if is_valid(ema20_w) and current_price < ema20_w:
            multiplier += 0.5
            signals.append("Sotto EMA20 Weekly")
            
        if is_valid(mayer_d):
            if mayer_d < alt_mayer_low:
                multiplier += 0.5
                signals.append(f"Mayer < {alt_mayer_low} ({round(mayer_d,2)})")
            elif mayer_d > alt_mayer_high:
                multiplier -= 0.5
                signals.append(f"Mayer > {alt_mayer_high} ({round(mayer_d,2)})")

    multiplier = max(0.0, multiplier)
    return {"multiplier": multiplier, "signals": signals if signals else ["Nessun segnale macro di rilievo"]}

def get_crypto_ta(symbol, timeframe="1d", period="5y", dca_params=None):
    """
    Scarica lo storico prezzi da Yahoo Finance e calcola 
    RSI, EMA 20, EMA 50 e definisce il trend.
    """
    # Aggiungi -EUR se il simbolo non ha una coppia specificata (es: BTC -> BTC-EUR)
    if "-" not in symbol:
        yf_symbol = f"{symbol}-EUR"
    else:
        yf_symbol = symbol

    try:
        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(period=period, interval=timeframe)
        
        if hist.empty or len(hist) < 50:
            return {
                "current_price": "N/A",
                "trend": "Unknown",
                "rsi": "N/A",
                "ema_20": "N/A",
                "ema_50": "N/A",
                "patterns": ["Dati Insufficienti"]
            }

        # Calcoli semplici pandas puri per il daily
        hist['RSI_14'] = compute_rsi(hist, periods=14)
        hist['EMA_20'] = hist['Close'].ewm(span=20, adjust=False).mean()
        hist['EMA_50'] = hist['Close'].ewm(span=50, adjust=False).mean()
        hist['SMA_200'] = hist['Close'].rolling(window=200).mean()
        hist['Mayer_Multiple'] = hist['Close'] / hist['SMA_200']

        # Creazione del dataframe settimanale per gli indicatori Smart DCA Macro
        # Resample basato sulla settimana (W-SUN è standard crypto)
        df_weekly = hist['Close'].resample('W-SUN').last().to_frame()
        df_weekly['RSI_14_W'] = compute_rsi(df_weekly, periods=14)
        df_weekly['EMA_20_W'] = df_weekly['Close'].ewm(span=20, adjust=False).mean()
        df_weekly['SMA_200_W'] = df_weekly['Close'].rolling(window=200).mean()

        last_row = hist.iloc[-1]
        last_w_row = df_weekly.iloc[-1] if not df_weekly.empty else None
        
        # Current values Daily
        current_price = round(last_row["Close"], 4)
        rsi = round(last_row["RSI_14"], 2) if not pd.isna(last_row["RSI_14"]) else "N/A"
        ema_20 = round(last_row["EMA_20"], 4) if not pd.isna(last_row["EMA_20"]) else "N/A"
        ema_50 = round(last_row["EMA_50"], 4) if not pd.isna(last_row["EMA_50"]) else "N/A"
        mayer_d = last_row["Mayer_Multiple"] if not pd.isna(last_row["Mayer_Multiple"]) else "N/A"
        
        # Current values Weekly
        if last_w_row is not None:
            rsi_w = last_w_row["RSI_14_W"] if not pd.isna(last_w_row["RSI_14_W"]) else "N/A"
            ema20_w = last_w_row["EMA_20_W"] if not pd.isna(last_w_row["EMA_20_W"]) else "N/A"
            wma200_w = last_w_row["SMA_200_W"] if not pd.isna(last_w_row["SMA_200_W"]) else "N/A"
        else:
            rsi_w, ema20_w, wma200_w = "N/A", "N/A", "N/A"
        
        # Trend elementare Daily
        if ema_20 != "N/A" and ema_50 != "N/A":
            if ema_20 > ema_50:
                trend_status = "Bullish (EMA20 > EMA50)"
            elif ema_20 < ema_50:
                trend_status = "Bearish (EMA20 < EMA50)"
            else:
                trend_status = "Neutral"
        else:
            trend_status = "Unknown"
            
        # Calcolo logica Smart DCA con parametri configurabili
        smart_dca = get_dca_multiplier(symbol, current_price, rsi_w, ema20_w, wma200_w, mayer_d, dca_params)
            
        # Optional Patterns based on simple RSI thresholds
        patterns = []
        if rsi != "N/A":
            if rsi < 30:
                patterns.append("Oversold (Ipervenduto)")
            elif rsi > 70:
                patterns.append("Overbought (Ipercomprato)")
        
        # Calcolo Volatilita (dev standard ritorni percentuali) come richiesto da Knowledge Base
        hist['Returns'] = hist['Close'].pct_change()
        str_volatility = hist['Returns'].std() * 100
        daily_vol_str = round(str_volatility, 2) if pd.notna(str_volatility) else 0.0
        
        # Volatility spike check odierno (High-Low)
        today_volatility = ((last_row["High"] - last_row["Low"]) / last_row["Close"]) * 100
        if today_volatility > 5:
            patterns.append(f"Spike Volatilita' Giornaliera ({round(today_volatility,1)}%)")

        # Configurazione Volume (Elemento cardine della VPA)
        vol_source = "Yahoo Finance"
        current_vol = last_row["Volume"] if "Volume" in hist.columns else 0
        avg_vol = 0
        
        try:
            import os
            # 1. Tenta fetch via CoinGecko (molto più affidabile per crypto)
            from pycoingecko import CoinGeckoAPI
            
            cg_key = os.getenv("COINGECKO_API_KEY")
            if cg_key:
                # Dalla doc di v3.x di pycoingecko, il parametro demo_api_key espande il limite
                cg = CoinGeckoAPI(demo_api_key=cg_key)
            else:
                cg = CoinGeckoAPI()
            
            # Ricerca l'ID esatto della moneta in base al simbolo
            # Visto che alcuni simboli possono essere duplicati, prendiamo solo le top hits più logiche (primo match)
            search_res = cg.search(symbol)
            if search_res and "coins" in search_res and len(search_res["coins"]) > 0:
                cg_id = search_res["coins"][0]["id"]
                
                # Prendi volumi ultimi 30 giorni daily
                cg_data = cg.get_coin_market_chart_by_id(id=cg_id, vs_currency='eur', days='30', interval='daily')
                v_list = cg_data.get('total_volumes', [])
                
                if len(v_list) > 0:
                    vols_only = [item[1] for item in v_list]
                    current_vol = vols_only[-1]
                    # Conta gli ultimi ~20 o meno
                    period_count = min(20, len(vols_only))
                    avg_vol = sum(vols_only[-period_count:]) / period_count
                    vol_source = f"CoinGecko ({cg_id})"
                else:
                    raise Exception("Lista volumi vuota da CoinGecko")
            else:
                raise Exception("Token non trovato in libreria CoinGecko")
        
        except Exception as e:
            # Fallback a Yahoo: calcola la media dal DataFrame generato
            print(f"Fallback Yahoo Volume (Motivo CG error: {e})")
            if "Volume" in hist.columns and len(hist) > 0:
                hist['Vol_SMA_20'] = hist['Volume'].rolling(window=20).mean()
                avg_vol = hist.iloc[-1]["Vol_SMA_20"]

        # VPA Valutazione del Volume e Trend
        volume_trend = "LOW"
        vol_analysis = f"{current_vol:,.0f} [{vol_source}]"
        
        # Gestiamo casi dove non esiste il volume
        if current_vol == 0 and (pd.isna(avg_vol) or avg_vol == 0):
            vol_analysis = "Non Disponibile (Missing Volume Data)"
        elif not pd.isna(avg_vol) and avg_vol > 0:
            vol_ratio = current_vol / avg_vol
            
            # Soglia per trend alto stabilita a > 1.2x media
            if vol_ratio >= 1.2:
                volume_trend = "HIGH"
                
            if vol_ratio > 1.5:
                patterns.append(f"Volume Spike! ({round(vol_ratio, 1)}x la media a 20g)")
                vol_analysis += f" (Sopra la media, {round(vol_ratio,1)}x)"
            elif vol_ratio < 0.7:
                vol_analysis += " (Sotto la media)"
            else:
                vol_analysis += " (Nella media)"

        active_analysis = {
            "current_price": current_price,
            "trend": trend_status,
            "rsi": rsi,
            "ema_20": ema_20,
            "ema_50": ema_50,
            "sma_200": round(last_row["SMA_200"], 4) if "SMA_200" in last_row else "N/A",
            "daily_volatility": f"{daily_vol_str}%",
            "volume_info": vol_analysis,
            "volume_trend": volume_trend,
            "patterns": patterns,
            "smart_dca": smart_dca
        }

        return active_analysis

    except Exception as e:
        print(f"Errore TA su {yf_symbol}: {e}")
        return {
            "current_price": "N/A",
            "trend": "Unknown",
            "rsi": "N/A",
            "ema_20": "N/A",
            "ema_50": "N/A",
            "patterns": ["Errore calcolo TA"]
        }
