import streamlit as st
import yfinance as yf
import pandas as pd
import datetime

# --- Page Config ---
st.set_page_config(page_title="Daily ATR Calculator", layout="centered")

# --- Helper Functions ---

def get_pip_settings(pair):
    """
    Returns the pip unit and formatting precision.
    EUR/USD: 0.0001
    USD/JPY: 0.01
    """
    if "JPY" in pair:
        return 0.01, "{:.3f}", "{:.1f}"
    else:
        return 0.0001, "{:.5f}", "{:.1f}"

def fetch_data(symbol):
    # 1. Get Daily History for ATR (last 3 months to be safe)
    daily_df = yf.download(symbol, period="3mo", interval="1d", progress=False)
    # 2. Get Live Minute Data for Price (last 1 day)
    live_df = yf.download(symbol, period="1d", interval="1m", progress=False)
    return daily_df, live_df

def calculate_daily_atr(df, period=14):
    df['h_l'] = df['High'] - df['Low']
    df['h_pc'] = (df['High'] - df['Close'].shift(1)).abs()
    df['l_pc'] = (df['Low'] - df['Close'].shift(1)).abs()
    df['TR'] = df[['h_l', 'h_pc', 'l_pc']].max(axis=1)
    df['ATR'] = df['TR'].rolling(window=period).mean()
    return df

# --- UI Layout ---

st.title("Standard Daily ATR Calculator")

# --- Sidebar Inputs ---
with st.sidebar:
    st.header("Settings")
    pair_option = st.radio("Select Pair", ["EUR/USD", "USD/JPY"])
    
    st.divider()
    
    # CHANGED: Step size is now 0.01
    sl_mult = st.number_input("SL Multiplier", value=0.50, step=0.01, format="%.2f")
    tp_mult = st.number_input("TP Multiplier", value=1.00, step=0.01, format="%.2f")

# --- Main Logic ---

symbol_map = {"EUR/USD": "EURUSD=X", "USD/JPY": "JPY=X"}
ticker = symbol_map[pair_option]
pip_unit, price_fmt, pip_fmt = get_pip_settings(pair_option)

if st.button("Get Live Data", type="primary"):
    
    try:
        with st.spinner("Syncing..."):
            daily_data, live_data = fetch_data(ticker)
        
        if daily_data.empty or live_data.empty:
            st.error("Market data unavailable.")
        else:
            # 1. Calculate ATR
            daily_data = calculate_daily_atr(daily_data)
            current_atr_val = float(daily_data['ATR'].iloc[-1])
            atr_in_pips = current_atr_val / pip_unit
            
            # 2. Get Live Price
            current_price = float(live_data['Close'].iloc[-1])
            last_date = daily_data.index[-1].strftime("%Y-%m-%d")

            # --- Metrics Display ---
            st.divider()
            m1, m2, m3 = st.columns(3)
            m1.metric("Live Price", price_fmt.format(current_price))
            m2.metric("Daily ATR", f"{pip_fmt.format(atr_in_pips)} pips")
            m3.metric("Date", last_date)
            
            # --- Calculation ---
            sl_dist = current_atr_val * sl_mult
            tp_dist = current_atr_val * tp_mult
            
            # Long Calcs
            long_sl = current_price - sl_dist
            long_tp = current_price + tp_dist
            
            # Short Calcs
            short_sl = current_price + sl_dist
            short_tp = current_price - tp_dist

            # --- NEW: Simplified Table Display ---
            st.subheader("Calculated Targets")

            # Create a simple list of dictionaries for the table
            table_data = [
                {
                    "Direction": "LONG (Buy)",
                    "Stop Loss": price_fmt.format(long_sl),
                    "Take Profit": price_fmt.format(long_tp)
                },
                {
                    "Direction": "SHORT (Sell)",
                    "Stop Loss": price_fmt.format(short_sl),
                    "Take Profit": price_fmt.format(short_tp)
                }
            ]

            # Display as a clean, static table
            st.table(table_data)
                
    except Exception as e:
        st.error(f"Error: {e}")