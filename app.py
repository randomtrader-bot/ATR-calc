import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import pytz
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time, timedelta

# --- Page Configuration ---
st.set_page_config(page_title="Forex Safety Shield", layout="centered", page_icon="🛡️")

# --- Constants & Configuration ---
USER_TIMEZONE = pytz.timezone('Europe/Riga')
NEWS_URL = "https://finviz.com/calendar.ashx"

# Whitelist: Critical Events + Liquidity Killers + Job Titles
IMPORTANT_KEYWORDS = [
    # Inflation & Economy
    "CPI", "Consumer Price Index",
    "PPI", "Producer Price Index",
    "PCE", "Personal Consumption Expenditures",
    "GDP", "Gross Domestic Product",
    "ISM", "Institute for Supply Management",
    "Retail Sales",
    "Consumer Confidence", "Sentiment",
    
    # Labor Market
    "Nonfarm", "Non-Farm", "Payroll",
    "Unemployment Rate",
    "JOLTS", "Job Openings",
    
    # Central Bank & Policy
    "Interest Rate", "Policy Rate", "Minimum Bid Rate",
    "FOMC", "Monetary Policy",
    "Minutes", "Meeting Minutes",
    
    # Auctions (USD/JPY Movers)
    "Bond Auction", "Note Auction",
    
    # Speakers & Titles (Specific Ranks Only)
    "Testifies", 
    "Chair", "Vice Chair",
    "President",
    "Governor", "Gov",
    
    # Liquidity / Market Conditions
    "Holiday", "Closed", "Observance" 
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# --- Helper Functions ---

def get_pip_unit(pair):
    if "JPY" in pair: return 0.01
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

# --- Data Engine 1: News (Cached 1h) ---

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_news(pair, is_weekend):
    relevant_currencies = pair.split("/")
    upcoming = []
    passed = []
    fetch_time = datetime.now(USER_TIMEZONE).strftime("%H:%M")
    
    try:
        response = requests.get(NEWS_URL, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            return [], [], True, fetch_time
            
        soup = BeautifulSoup(response.content, "html.parser")
        rows = soup.find_all("tr", class_="calendar-row")
        
        # Anti-Captcha Check (Weekday only)
        if not is_weekend and len(rows) == 0:
             return [], [], True, fetch_time 

        current_riga_time = datetime.now(USER_TIMEZONE)
        
        # Lookahead Logic: 72h on Weekends, 24h on Weekdays
        lookahead_seconds = 259200 if is_weekend else 86400

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
            
            # Filter 3: Time Conversion & Safety Parsing
            event_dt = convert_to_latvia_time(time_text)
            is_tentative = False
            
            if event_dt is None:
                if "tentative" in time_text.lower() or "all day" in time_text.lower():
                    is_tentative = True
                    display_time = "⚠️ Tentative"
                else:
                    continue 
            else:
                # Filter 4: Dynamic Lookahead
                if abs((event_dt - current_riga_time).total_seconds()) > lookahead_seconds:
                    continue
                display_time = event_dt.strftime("%A %H:%M") if is_weekend else event_dt.strftime("%H:%M")
            
            event_obj = {"time": display_time, "currency": currency, "event": event_name}
            
            if is_tentative:
                upcoming.append(event_obj)
            elif current_riga_time > (event_dt + timedelta(minutes=60)):
                passed.append(event_obj)
            else:
                upcoming.append(event_obj)
                
        return upcoming, passed, False, fetch_time
        
    except Exception as e:
        return [], [], True, fetch_time

# --- Data Engine 2: Market Data (Cached 30m) ---

@st.cache_data(ttl=1800, show_spinner=False)
def get_market_data(symbol, pip_unit):
    try:
        # 1. Fetch Daily Data (For ATR)
        df_daily = yf.download(symbol, period="2mo", interval="1d", progress=False, auto_adjust=False)
        if isinstance(df_daily.columns, pd.MultiIndex):
            df_daily.columns = df_daily.columns.get_level_values(0)
            
        # 2. Fetch M30 Data (For RSI)
        df_m30 = yf.download(symbol, period="5d", interval="30m", progress=False, auto_adjust=False)
        if isinstance(df_m30.columns, pd.MultiIndex):
            df_m30.columns = df_m30.columns.get_level_values(0)

        if df_daily.empty or df_m30.empty: 
            return {"error": "No data returned from Yahoo Finance."}
        
        # FIX 2: Timezone Aware Freshness Check
        # Convert index to UTC explicitly to compare apples-to-apples
        last_candle_time = df_m30.index[-1]
        if last_candle_time.tzinfo is None:
             last_candle_time = last_candle_time.replace(tzinfo=pytz.utc)
        else:
             last_candle_time = last_candle_time.astimezone(pytz.utc)
        
        now_utc = datetime.now(pytz.utc)
        candle_age_minutes = (now_utc - last_candle_time).total_seconds() / 60
        
        is_stale = False
        if candle_age_minutes > 20: 
            is_stale = True
        
        # --- CALC 1: Daily ATR (14) ---
        df_daily['h_l'] = df_daily['High'] - df_daily['Low']
        df_daily['h_pc'] = (df_daily['High'] - df_daily['Close'].shift(1)).abs()
        df_daily['l_pc'] = (df_daily['Low'] - df_daily['Close'].shift(1)).abs()
        df_daily['TR'] = df_daily[['h_l', 'h_pc', 'l_pc']].max(axis=1)
        df_daily['ATR'] = df_daily['TR'].rolling(window=14).mean()
        
        current_atr_val = float(df_daily['ATR'].iloc[-2])
        
        # --- CALC 2: M30 RSI (14) ---
        df_m30['RSI'] = calculate_rsi(df_m30['Close'])
        current_rsi = float(df_m30['RSI'].iloc[-1])
        
        return {
            "atr_pips": current_atr_val / pip_unit,
            "rsi_m30": current_rsi,
            "is_stale": is_stale, 
            "error": None
        }
    except Exception as e:
        return {"error": str(e)}

# --- MAIN APP UI ---

# Refresh Button
c_refresh, c_title = st.columns([1, 3])
with c_refresh:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
with c_title:
    st.title("Forex Shield")

# Robust Session State for Pair Selection
if "pair_selection" not in st.session_state:
    st.session_state.pair_selection = "EUR/USD"

def update_pair():
    st.session_state.pair_selection = st.session_state.pair_widget

# 1. Top Control Bar
col_pair, col_link = st.columns([2, 1])
with col_pair:
    current_index = 0 if st.session_state.pair_selection == "EUR/USD" else 1
    
    pair_option = st.radio(
        "Select Pair:", 
        ["EUR/USD", "USD/JPY"], 
        horizontal=True, 
        index=current_index,
        key="pair_widget", 
        on_change=update_pair
    )

with col_link:
    st.markdown("")
    st.markdown("")
    st.markdown("[🔍 **Verify**](https://www.forexfactory.com/calendar)", unsafe_allow_html=True)

# Source of Truth
symbol_map = {"EUR/USD": "EURUSD=X", "USD/JPY": "JPY=X"}
ticker = symbol_map[st.session_state.pair_selection]
pip_unit = get_pip_unit(st.session_state.pair_selection)

st.divider()

# --- WEEKEND CHECK ---
now_latvia = datetime.now(USER_TIMEZONE)
# Saturday = 5, Sunday = 6
is_weekend = now_latvia.weekday() >= 5

# --- SECTION 1: SAFETY CHECKS ---
st.subheader("Environment Status")

# A. Rollover Check (US Eastern Time)
ny_tz = pytz.timezone('US/Eastern')
now_ny = datetime.now(ny_tz)

ny_minutes = now_ny.hour * 60 + now_ny.minute
start_minutes = 16 * 60 + 50 # 16:50 NY
end_minutes = 18 * 60 + 5    # 18:05 NY

is_rollover = False
if start_minutes <= ny_minutes <= end_minutes:
    is_rollover = True

# B. Data Fetching
upcoming_news, passed_news, news_error, last_update = fetch_news(st.session_state.pair_selection, is_weekend)

# Fetch market data ONLY if weekday (saves resources/errors on weekends)
market_data = None
if not is_weekend:
    market_data = get_market_data(ticker, pip_unit)

# --- MASTER STATUS DISPLAY ---
st.caption(f"App Time: {now_latvia.strftime('%H:%M:%S')} (Riga) | News Check: {last_update}")

market_data_healthy = market_data and not market_data.get('error')

if is_weekend:
    st.info("⚪ **MARKET CLOSED (Weekend)**")
    st.markdown("Showing News Calendar for next 72 hours.")

elif is_rollover:
    st.error("⚫ **NO TRADE (Rollover)**")
    st.markdown("Spreads are wide (NY Time 16:50 - 18:05). Scalping is impossible.")

elif news_error:
    st.warning("⚠️ **Connection Failed (Scraper Blocked).** Check ForexFactory manually.")

elif upcoming_news:
    st.error(f"⚠️ **DANGER: High Impact News ({len(upcoming_news)})**")
    for news in upcoming_news:
        st.write(f"**{news['time']}** | {news['event']}")

elif not market_data_healthy:
    st.warning("⚠️ **System Error: Market Data Failed**")
    st.markdown("RSI/ATR could not be loaded. Trade with caution.")

elif market_data.get('is_stale'):
    st.warning("⚠️ **Market Data Delayed**")
    st.markdown("Yahoo Finance data is >20 mins old. RSI is not real-time.")

else:
    st.success("✅ **SAFE TO TRADE**")
    st.caption("No News. No Spread Spikes. Data Feed Live.")

if passed_news:
    with st.expander("Show Completed Events (Today)"):
        for news in passed_news:
            st.markdown(f"<span style='color:grey'>✅ {news['time']} - {news['event']} (Passed)</span>", unsafe_allow_html=True)

st.divider()

# --- WEEKEND HIDE: RSI & ATR are hidden on Sat/Sun ---
if not is_weekend:

    # --- SECTION 2: MOMENTUM GAUGE (M30 RSI) ---
    if market_data:
        if market_data.get('error'):
            st.error(f"Data Error: {market_data['error']}")
        else:
            rsi = market_data['rsi_m30']
            
            st.subheader("Momentum (M30 - Live Candle)")
            
            if rsi < 25:
                 st.error(f"### 🛑 EXTREME DOWN (RSI {rsi:.0f})")
                 st.markdown("**Market Stretched.** Volatility is high. Wait for stabilization.")
                 
            elif rsi < 30:
                st.success(f"### 🟢 OVERSOLD (RSI {rsi:.0f})")
                st.markdown("**Price Extended.** Monitor structure for reactions.")
                
            elif rsi > 75:
                 st.error(f"### 🛑 EXTREME UP (RSI {rsi:.0f})")
                 st.markdown("**Market Stretched.** Volatility is high. Wait for stabilization.")
                 
            elif rsi > 70:
                st.warning(f"### 🔴 OVERBOUGHT (RSI {rsi:.0f})")
                st.markdown("**Price Extended.** Monitor structure for reactions.")
                
            else:
                st.info(f"### ⚪ NORMAL (RSI {rsi:.0f})")
                st.caption("Momentum is neutral. Rely on Structure.")
    else:
        st.error("System Error: Could not verify Market Data.")

    st.divider()

    # --- SECTION 3: ATR CALCULATOR ---
    if market_data and not market_data.get('error'):
        atr_pips = market_data['atr_pips']
        
        st.subheader("Risk Sizing (Daily ATR)")
        
        def update_params():
            st.query_params["sl"] = st.session_state.sl_mult
            st.query_params["tp"] = st.session_state.tp_mult

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
