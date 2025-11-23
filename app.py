import streamlit as st
import yfinance as yf
import pandas as pd
import pytz
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# --- Page Configuration ---
st.set_page_config(page_title="Forex Risk Tool", layout="centered")

# --- Constants & Configuration ---
USER_TIMEZONE = pytz.timezone('Europe/Riga')
NEWS_URL = "https://finviz.com/calendar.ashx"

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

def convert_to_latvia_time(time_str_est):
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

# --- Data Fetching ---

@st.cache_data(ttl=1800, show_spinner=False)
def get_daily_atr_pips(symbol, pip_unit):
    try:
        df = yf.download(symbol, period="3mo", interval="1d", progress=False)
        if df.empty: return None
        
        df['h_l'] = df['High'] - df['Low']
        df['h_pc'] = (df['High'] - df['Close'].shift(1)).abs()
        df['l_pc'] = (df['Low'] - df['Close'].shift(1)).abs()
        df['TR'] = df[['h_l', 'h_pc', 'l_pc']].max(axis=1)
        df['ATR'] = df['TR'].rolling(window=14).mean()
        
        current_atr_price = float(df['ATR'].iloc[-1])
        return current_atr_price / pip_unit
    except:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_news(pair):
    relevant_currencies = pair.split("/")
    upcoming = []
    passed = []
    
    try:
        response = requests.get(NEWS_URL, headers=HEADERS)
        if response.status_code != 200: return [], [], True
            
        soup = BeautifulSoup(response.content, "html.parser")
        rows = soup.find_all("tr", class_="calendar-row")
        current_riga_time = datetime.now(USER_TIMEZONE)

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 4: continue
            
            time_text = cols[0].text.strip()
            currency = cols[1].text.strip()
            event_name = cols[3].text.strip()
            
            if currency not in relevant_currencies: continue
            is_important = any(k.lower() in event_name.lower() for k in IMPORTANT_KEYWORDS)
            if not is_important: continue
            
            event_dt = convert_to_latvia_time(time_text)
            if event_dt is None: continue
            
            display_time = event_dt.strftime("%H:%M")
            event_obj = {"time": display_time, "currency": currency, "event": event_name, "dt_object": event_dt}
            
            if current_riga_time > (event_dt + timedelta(minutes=60)):
                passed.append(event_obj)
            else:
                upcoming.append(event_obj)
                
        return upcoming, passed, False
    except:
        return [], [], True

# --- Main App Interface ---

st.title("🛡️ Forex Risk Tool")

# 1. Pair Selection
col_pair, col_link = st.columns([2, 1])
with col_pair:
    pair_option = st.radio("Select Pair:", ["EUR/USD", "USD/JPY"], horizontal=True)
with col_link:
    st.markdown("")
    st.markdown("")
    st.markdown("[Verify on ForexFactory](https://www.forexfactory.com/calendar)", unsafe_allow_html=True)

symbol_map = {"EUR/USD": "EURUSD=X", "USD/JPY": "JPY=X"}
ticker = symbol_map[pair_option]
pip_unit = get_pip_unit(pair_option)

st.divider()

# 2. News Logic
upcoming_news, passed_news, news_error = fetch_news(pair_option)

if news_error:
    st.warning("⚠️ Could not load News Data. Please verify manually.")
elif upcoming_news:
    st.error(f"⚠️ **CAUTION: {len(upcoming_news)} High Impact Events Upcoming**")
    for news in upcoming_news:
        st.write(f"**{news['time']}** ({news['currency']}) - {news['event']}")
else:
    st.success("✅ **Clear Skies (Upcoming 24h)**")
    st.caption("No critical keywords found in upcoming schedule.")

if passed_news:
    with st.expander("Show Completed Events (Today)"):
        for news in passed_news:
            st.markdown(f"<span style='color:grey'>✅ {news['time']} - {news['event']} (Passed)</span>", unsafe_allow_html=True)

st.divider()

# 3. ATR & Calculator (FIXED LOGIC HERE)
atr_pips = get_daily_atr_pips(ticker, pip_unit)

if atr_pips is None:
    st.error("Error loading ATR data.")
else:
    st.subheader("Volatility Targets")
    
    # --- FIXED STATE MANAGEMENT ---
    # This callback saves the numbers to URL ONLY when you change them
    def update_params():
        st.query_params["sl"] = st.session_state.sl_mult
        st.query_params["tp"] = st.session_state.tp_mult

    # Initialize Session State from URL (Runs only once on load)
    if "sl_mult" not in st.session_state:
        qp = st.query_params
        st.session_state.sl_mult = float(qp.get("sl", 0.50))
        st.session_state.tp_mult = float(qp.get("tp", 1.00))

    c1, c2 = st.columns(2)
    with c1:
        # We bind the widget to session_state using 'key'
        st.number_input("SL Multiplier", key="sl_mult", step=0.01, format="%.2f", on_change=update_params)
    with c2:
        st.number_input("TP Multiplier", key="tp_mult", step=0.01, format="%.2f", on_change=update_params)
        
    # Calculation uses the session state directly
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

    st.caption(f"Based on Daily ATR: {atr_pips:.1f} pips")
