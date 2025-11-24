import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import pytz
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# --- Page Configuration ---
st.set_page_config(page_title="Forex Risk Dashboard", layout="centered", page_icon="🛡️")

# --- Configuration & Constants ---
USER_TIMEZONE = pytz.timezone('Europe/Riga')
NEWS_URL = "https://finviz.com/calendar.ashx"

# The "White List" - App only cares about these events
IMPORTANT_KEYWORDS = [
    "CPI", "Consumer Price Index",
    "GDP", "Gross Domestic Product",
    "Nonfarm", "Non-Farm", "Payroll",
    "Unemployment Rate",
    "Interest Rate", "Policy Rate", "Minimum Bid Rate",
    "FOMC", "Monetary Policy",
    "Speaks", "Testifies", "Chair", "President"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# --- Helper Functions ---

def get_pip_unit(pair):
    if "JPY" in pair:
        return 0.01
    return 0.0001

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def convert_to_latvia_time(time_str_est):
    """Converts Finviz EST time to Europe/Riga Time"""
    try:
        est = pytz.timezone('US/Eastern')
        today = datetime.now(est).date()
        dt_str = f"{today} {time_str_est}"
        dt_est = datetime.strptime(dt_str, "%Y-%m-%d %I:%M %p")
        dt_est = est.localize(dt_est)
        dt_riga = dt_est.astimezone(USER_TIMEZONE)
        return dt_riga
    except:
        return None

# --- Data Engine 1: News Scraper (Cached 1h) ---

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_news(pair):
    relevant_currencies = pair.split("/")
    upcoming = []
    passed = []
    fetch_time = datetime.now(USER_TIMEZONE).strftime("%H:%M")
    
    try:
        response = requests.get(NEWS_URL, headers=HEADERS, timeout=5)
        if response.status_code != 200:
            return [], [], True, fetch_time
            
        soup = BeautifulSoup(response.content, "html.parser")
        rows = soup.find_all("tr", class_="calendar-row")
        current_riga_time = datetime.now(USER_TIMEZONE)

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 4: continue
            
            time_text = cols[0].text.strip()
            currency = cols[1].text.strip()
            event_name = cols[3].text.strip()
            
            # Filter 1: Currency Match
            if currency not in relevant_currencies: continue
            
            # Filter 2: Keywords Match
            is_important = any(k.lower() in event_name.lower() for k in IMPORTANT_KEYWORDS)
            if not is_important: continue
            
            # Filter 3: Time Conversion
            event_dt = convert_to_latvia_time(time_text)
            if event_dt is None: continue
            
            # Filter 4: 24-Hour Lookahead Only
            # If event is older than 24h or more than 24h in future, ignore
            if abs((event_dt - current_riga_time).total_seconds()) > 86400:
                continue
            
            display_time = event_dt.strftime("%H:%M")
            event_obj = {"time": display_time, "currency": currency, "event": event_name}
            
            # Sort: Passed (>1h ago) vs Upcoming/Active
            if current_riga_time > (event_dt + timedelta(minutes=60)):
                passed.append(event_obj)
            else:
                upcoming.append(event_obj)
                
        return upcoming, passed, False, fetch_time
        
    except Exception as e:
        return [], [], True, fetch_time

# --- Data Engine 2: Technical Analysis (Cached 30m) ---

@st.cache_data(ttl=1800, show_spinner=False)
def get_technical_analysis(symbol, pip_unit):
    try:
        # Fetch data (6mo for valid moving averages)
        df = yf.download(symbol, period="6mo", interval="1d", progress=False)
        if df.empty: return None
        
        # 1. ATR Calculation (14)
        df['h_l'] = df['High'] - df['Low']
        df['h_pc'] = (df['High'] - df['Close'].shift(1)).abs()
        df['l_pc'] = (df['Low'] - df['Close'].shift(1)).abs()
        df['TR'] = df[['h_l', 'h_pc', 'l_pc']].max(axis=1)
        df['ATR'] = df['TR'].rolling(window=14).mean()
        
        # 2. SMA 50 (Trend)
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        
        # 3. RSI 14 (Momentum)
        df['RSI'] = calculate_rsi(df['Close'])
        
        # 4. Current Day Stats
        latest = df.iloc[-1]
        atr_val = float(latest['ATR'])
        current_close = float(latest['Close'])
        sma_val = float(latest['SMA_50'])
        rsi_val = float(latest['RSI'])
        
        # 5. ADR Exhaustion Logic
        # Today's Range (High - Low)
        todays_range = float(latest['High'] - latest['Low'])
        adr_usage_pct = (todays_range / atr_val) * 100
        
        return {
            "atr_pips": atr_val / pip_unit,
            "current_price": current_close,
            "sma_50": sma_val,
            "rsi": rsi_val,
            "adr_usage": adr_usage_pct
        }
    except:
        return None

# --- MAIN APP UI ---

st.title("🛡️ Forex Risk Dashboard")

# 1. Top Control Bar
col_pair, col_link = st.columns([2, 1])
with col_pair:
    pair_option = st.radio("Select Pair:", ["EUR/USD", "USD/JPY"], horizontal=True)
with col_link:
    st.markdown("")
    st.markdown("")
    st.markdown("[🔍 **Verify News**](https://www.forexfactory.com/calendar)", unsafe_allow_html=True)

symbol_map = {"EUR/USD": "EURUSD=X", "USD/JPY": "JPY=X"}
ticker = symbol_map[pair_option]
pip_unit = get_pip_unit(pair_option)

st.divider()

# --- SECTION 2: NEWS FILTER ---
upcoming_news, passed_news, news_error, last_update = fetch_news(pair_option)

# Health Monitor Label
st.caption(f"News Last Check: {last_update} (Latvia Time)")

if news_error:
    st.warning("⚠️ **Connection Failed:** News data could not be verified. Do not trust the 'Clear Skies' signal. Check ForexFactory manually.")
elif upcoming_news:
    st.error(f"⚠️ **CAUTION: {len(upcoming_news)} High Impact Events Upcoming/Active**")
    for news in upcoming_news:
        st.markdown(f"**{news['time']}** | {news['currency']} | {news['event']}")
else:
    st.success("✅ **Clear Skies (Next 24h)**")

if passed_news:
    with st.expander("Show Completed Events (Today)"):
        for news in passed_news:
            st.markdown(f"<span style='color:grey'>✅ {news['time']} - {news['event']} (Passed)</span>", unsafe_allow_html=True)

st.divider()

# --- SECTION 3: MASTER SIGNAL (Context) ---
tech_data = get_technical_analysis(ticker, pip_unit)

if tech_data is None:
    st.error("Error loading market data.")
else:
    # Unpack variables for cleaner logic
    price = tech_data['current_price']
    sma = tech_data['sma_50']
    atr_pips = tech_data['atr_pips']
    rsi = tech_data['rsi']
    adr_usage = tech_data['adr_usage']
    
    # Calculate Buffer (Rotation Zone) in Price Terms
    # 0.5 * ATR in price units (not pips)
    buffer = 0.5 * (atr_pips * pip_unit)
    
    # --- THE MASTER LOGIC CHAIN ---
    
    signal_color = "black"
    signal_title = "NO TRADE"
    signal_reason = "Unknown"
    
    # Step 1: Check Fuel (ADR)
    if adr_usage > 100:
        signal_color = "black"
        signal_title = "NO TRADE (Exhausted)"
        signal_reason = f"Market has moved {adr_usage:.0f}% of daily range. Fuel is empty."
        
    else:
        # Step 2: Check Trend & Consolidation
        if price > (sma + buffer):
            # Potential Uptrend
            trend_status = "UP"
        elif price < (sma - buffer):
            # Potential Downtrend
            trend_status = "DOWN"
        else:
            # Inside Buffer
            trend_status = "FLAT"
            
        # Step 3: Check Momentum (RSI) & Final Signal
        if trend_status == "FLAT":
            signal_color = "orange"
            signal_title = "CONSOLIDATION"
            signal_reason = "Price is rotating near the 50-SMA. Range trading only."
            
        elif trend_status == "UP":
            if rsi > 70:
                signal_color = "black"
                signal_title = "NO TRADE (Overbought)"
                signal_reason = f"Trend is Up, but RSI is {rsi:.0f} (Too high). Wait for pullback."
            else:
                signal_color = "green"
                signal_title = "LONG TRADES ONLY"
                signal_reason = f"Bullish Trend + Healthy Momentum (RSI {rsi:.0f})."
                
        elif trend_status == "DOWN":
            if rsi < 30:
                signal_color = "black"
                signal_title = "NO TRADE (Oversold)"
                signal_reason = f"Trend is Down, but RSI is {rsi:.0f} (Too low). Wait for pullback."
            else:
                signal_color = "red"
                signal_title = "SHORT TRADES ONLY"
                signal_reason = f"Bearish Trend + Healthy Momentum (RSI {rsi:.0f})."

    # --- DISPLAY MASTER SIGNAL ---
    st.subheader("Market Context")
    
    if signal_color == "green":
        st.success(f"### 🟢 {signal_title}")
    elif signal_color == "red":
        st.error(f"### 🔴 {signal_title}")
    elif signal_color == "orange":
        st.warning(f"### 🟡 {signal_title}")
    else:
        st.info(f"### ⚫ {signal_title}")
        
    st.markdown(f"**Analysis:** {signal_reason}")
    st.caption(f"ADR Usage: {adr_usage:.0f}% | RSI: {rsi:.0f} | SMA Distance: {abs(price-sma)/pip_unit:.0f} pips")

    st.divider()

    # --- SECTION 4: CALCULATOR ---
    st.subheader("Volatility Targets")
    
    # Callback to prevent glitching
    def update_params():
        st.query_params["sl"] = st.session_state.sl_mult
        st.query_params["tp"] = st.session_state.tp_mult

    # Initialize Session State
    if "sl_mult" not in st.session_state:
        qp = st.query_params
        st.session_state.sl_mult = float(qp.get("sl", 0.50))
        st.session_state.tp_mult = float(qp.get("tp", 1.00))

    # Input Columns
    c1, c2 = st.columns(2)
    with c1:
        st.number_input("SL Multiplier", key="sl_mult", step=0.01, format="%.2f", on_change=update_params)
    with c2:
        st.number_input("TP Multiplier", key="tp_mult", step=0.01, format="%.2f", on_change=update_params)
        
    # Final Math
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
