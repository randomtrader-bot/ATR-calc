import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import pytz
from datetime import datetime, time

# --- Page Configuration ---
st.set_page_config(page_title="Forex Safety Shield", layout="centered", page_icon="🛡️")

# --- Constants ---
USER_TIMEZONE = pytz.timezone('Europe/Riga')

# --- Helper Functions ---

def get_pip_unit(pair):
    if "JPY" in pair: return 0.01
    return 0.0001

# --- Data Engine: Market Data (Cached 60s) ---

@st.cache_data(ttl=60, show_spinner=False)
def get_market_data(symbol, pip_unit):
    try:
        # 1. Fetch Daily Data (For ATR)
        # We fetch 3 months to ensure the Moving Average has enough data to stabilize
        df_daily = yf.download(symbol, period="3mo", interval="1d", progress=False, auto_adjust=False)
        
        # Flatten MultiIndex columns if present (yfinance bug fix)
        if isinstance(df_daily.columns, pd.MultiIndex):
            df_daily.columns = df_daily.columns.get_level_values(0)
            
        # Safety Check: Need at least 18 days for ATR calculation
        if df_daily.empty or len(df_daily) < 18: 
            return {"error": "Insufficient Daily Data."}
        
        # --- THE SUNDAY PURGE ---
        # Filter out Day 6 (Sunday) candles. 
        # This prevents low-volume Sunday sessions from dragging down the Monday average.
        # Monday calculation will now look back at Friday.
        df_daily = df_daily[df_daily.index.dayofweek != 6]

        # --- CALC 1: Daily ATR (14) ---
        df_daily['h_l'] = df_daily['High'] - df_daily['Low']
        df_daily['h_pc'] = (df_daily['High'] - df_daily['Close'].shift(1)).abs()
        df_daily['l_pc'] = (df_daily['Low'] - df_daily['Close'].shift(1)).abs()
        df_daily['TR'] = df_daily[['h_l', 'h_pc', 'l_pc']].max(axis=1)
        df_daily['ATR'] = df_daily['TR'].rolling(window=14).mean()
        
        # Use iloc[-2] (Yesterday's Closed Candle)
        # This ensures the number is stable and doesn't change while you trade today.
        current_atr_val = float(df_daily['ATR'].iloc[-2])
        
        return {
            "atr_pips": current_atr_val / pip_unit,
            "error": None
        }
    except Exception as e:
        return {"error": str(e)}

# --- MAIN APP UI ---

# Refresh Button (Clears Cache to force fresh data)
c_refresh, c_title = st.columns([1, 3])
with c_refresh:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
with c_title:
    st.title("Forex Shield")

# Session State for Pair Selection (Prevents reset bugs)
if "pair_selection" not in st.session_state:
    st.session_state.pair_selection = "EUR/USD"

def update_pair():
    st.session_state.pair_selection = st.session_state.pair_widget

# 1. Top Control Bar
current_index = 0 if st.session_state.pair_selection == "EUR/USD" else 1

pair_option = st.radio(
    "Select Pair:", 
    ["EUR/USD", "USD/JPY"], 
    horizontal=True, 
    index=current_index,
    key="pair_widget", 
    on_change=update_pair
)

# MANUAL VERIFY LINK (The Gatekeeper)
st.markdown("###")
st.link_button("📅 Open ForexFactory Calendar", "https://www.forexfactory.com/calendar")

# Source of Truth
symbol_map = {"EUR/USD": "EURUSD=X", "USD/JPY": "JPY=X"}
ticker = symbol_map[st.session_state.pair_selection]
pip_unit = get_pip_unit(st.session_state.pair_selection)

st.divider()

# --- WEEKEND CHECK ---
now_latvia = datetime.now(USER_TIMEZONE)
# Saturday=5, Sunday=6
is_weekend = now_latvia.weekday() >= 5

# --- SECTION 1: SAFETY CHECKS ---
st.subheader("Environment Status")

# A. Rollover Check (Dynamic based on US Eastern Time)
ny_tz = pytz.timezone('US/Eastern')
now_ny = datetime.now(ny_tz)

ny_minutes = now_ny.hour * 60 + now_ny.minute
start_minutes = 16 * 60 + 50 # 16:50 NY
end_minutes = 18 * 60 + 5    # 18:05 NY

is_rollover = False
if start_minutes <= ny_minutes <= end_minutes:
    is_rollover = True

# B. Data Fetching
market_data = None
if not is_weekend:
    market_data = get_market_data(ticker, pip_unit)

# --- MASTER STATUS DISPLAY ---
st.caption(f"App Time: {now_latvia.strftime('%H:%M:%S')} (Riga)")

market_data_healthy = market_data and not market_data.get('error')

if is_weekend:
    st.info("⚪ **MARKET CLOSED (Weekend)**")
    st.markdown("Enjoy the break.")

elif is_rollover:
    st.error("⚫ **NO TRADE (Rollover)**")
    st.markdown("Spreads are wide (NY Time 16:50 - 18:05). Scalping is impossible.")

elif not market_data_healthy:
    st.warning("⚠️ **System Error: Market Data Failed**")
    st.markdown("ATR could not be loaded. Trade with caution.")

else:
    st.success("✅ **SYSTEM READY**")
    st.caption("No Spread Spikes. Data Feed Live.")
    st.warning("⚠️ **DID YOU CHECK THE NEWS?**")

st.divider()

# --- SECTION 2: ATR CALCULATOR ---
# Hidden on Weekends to keep UI clean
if not is_weekend:
    if market_data and not market_data.get('error'):
        atr_pips = market_data['atr_pips']
        
        st.subheader("Risk Sizing (Daily ATR)")
        
        def update_params():
            st.query_params["sl"] = st.session_state.sl_mult
            st.query_params["tp"] = st.session_state.tp_mult

        # Load multipliers (Default to safe low values for scalping)
        if "sl_mult" not in st.session_state:
            qp = st.query_params
            st.session_state.sl_mult = float(qp.get("sl", 0.20))
            st.session_state.tp_mult = float(qp.get("tp", 0.15))

        c1, c2 = st.columns(2)
        with c1:
            st.number_input("SL Multiplier", key="sl_mult", step=0.01, format="%.2f", on_change=update_params)
        with c2:
            st.number_input("TP Multiplier", key="tp_mult", step=0.01, format="%.2f", on_change=update_params)
            
        sl_dist = atr_pips * st.session_state.sl_mult
        tp_dist = atr_pips * st.session_state.tp_mult

        st.markdown("---")
        res1, res2 = st.columns(2)
        with res1:
            st.markdown(f"<h3 style='text-align: center; color: #ff4b4b;'>STOP LOSS</h3>", unsafe_allow_html=True)
            st.markdown(f"<h2 style='text-align: center;'>{sl_dist:.1f} pips</h2>", unsafe_allow_html=True)
        with res2:
            st.markdown(f"<h3 style='text-align: center; color: #09ab3b;'>TAKE PROFIT</h3>", unsafe_allow_html=True)
            st.markdown(f"<h2 style='text-align: center;'>{tp_dist:.1f} pips</h2>", unsafe_allow_html=True)

        st.caption(f"Based on Daily ATR (14): {atr_pips:.1f} pips")
