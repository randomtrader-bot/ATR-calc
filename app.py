import streamlit as st
import yfinance as yf
import pandas as pd

# --- Page Configuration ---
st.set_page_config(page_title="Pip Distance Calculator", layout="centered")

# --- Helper Functions ---

def get_pip_unit(pair):
    """
    Returns the pip unit value.
    EUR/USD = 0.0001
    USD/JPY = 0.01
    """
    if "JPY" in pair:
        return 0.01
    return 0.0001

# --- Data Fetching (Cached) ---
# ttl=1800 means the cache lives for 1800 seconds (30 minutes).
# After 30 mins, the next user action triggers a new download.
@st.cache_data(ttl=1800, show_spinner=False)
def get_daily_atr_pips(symbol, pip_unit):
    """
    Downloads Daily data and returns the current 14-Day ATR in PIPS.
    """
    # Fetch 3 months to ensure plenty of data for the 14-day average
    df = yf.download(symbol, period="3mo", interval="1d", progress=False)
    
    if df.empty:
        return None

    # Calculate True Range
    df['h_l'] = df['High'] - df['Low']
    df['h_pc'] = (df['High'] - df['Close'].shift(1)).abs()
    df['l_pc'] = (df['Low'] - df['Close'].shift(1)).abs()
    df['TR'] = df[['h_l', 'h_pc', 'l_pc']].max(axis=1)
    
    # Calculate 14-Day ATR
    df['ATR'] = df['TR'].rolling(window=14).mean()
    
    # Get the latest ATR value
    current_atr_price = float(df['ATR'].iloc[-1])
    
    # Convert to Pips
    atr_in_pips = current_atr_price / pip_unit
    return atr_in_pips

# --- UI Layout ---

st.title("🛡️ ATR Risk Calculator")
st.markdown("Calculates **Stop Loss** and **Take Profit** distances in pips based on Daily Volatility.")

# --- 1. Settings (Top Section) ---
col_pair, col_atr = st.columns([1, 1])

with col_pair:
    pair_option = st.radio("Select Pair:", ["EUR/USD", "USD/JPY"], horizontal=True)

# Map selection to ticker
symbol_map = {"EUR/USD": "EURUSD=X", "USD/JPY": "JPY=X"}
ticker = symbol_map[pair_option]
pip_unit = get_pip_unit(pair_option)

# --- 2. Data Fetching (Automatic) ---
try:
    # This runs instantly if data is cached (under 30 mins old)
    atr_pips = get_daily_atr_pips(ticker, pip_unit)
    
    if atr_pips is None:
        st.error("Error: Could not fetch market data.")
    else:
        with col_atr:
            # Show the base ATR just for reference, small and grey
            st.metric(label="Market Volatility (Daily)", value=f"{atr_pips:.1f} pips")

        st.divider()

        # --- 3. Multipliers (The Control Panel) ---
        st.subheader("Multiplier Settings")
        
        c1, c2 = st.columns(2)
        
        with c1:
            # Step is 0.01 for precision
            sl_mult = st.number_input("SL Multiplier", value=0.50, step=0.01, format="%.2f")
        
        with c2:
            tp_mult = st.number_input("TP Multiplier", value=1.00, step=0.01, format="%.2f")

        # --- 4. The Results (Instant Calculation) ---
        
        # Calculate distances based on inputs
        final_sl_pips = atr_pips * sl_mult
        final_tp_pips = atr_pips * tp_mult

        st.divider()
        st.subheader("Target Distances")

        # Display Big Bold Metrics
        res_col1, res_col2 = st.columns(2)
        
        with res_col1:
            st.error(f"🛑 STOP LOSS\n# {final_sl_pips:.1f} pips")
            
        with res_col2:
            st.success(f"🎯 TAKE PROFIT\n# {final_tp_pips:.1f} pips")

except Exception as e:
    st.error(f"System Error: {e}")
