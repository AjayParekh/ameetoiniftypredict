import streamlit as st
import requests
import pandas as pd
from datetime import datetime, time
import datetime as dt_mod
import os
import pytz
from streamlit_autorefresh import st_autorefresh
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import warnings
warnings.filterwarnings('ignore')
import json
import calendar
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

access_token = 'Bearer eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIxMDM2NjciLCJqdGkiOiI2OWQyMzJlMWNjZDUyZDRjZDQzMzc5NjYiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlzRXh0ZW5kZWQiOnRydWUsImlhdCI6MTc3NTM4MzI2NSwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxODA2OTYyNDAwfQ.VFRZ5NP87NM1Vyn4-bCB2FAvanu4wsueNHo_POQtPv8'

# ==============================
# PAGE CONFIG
# ==============================
if "page_config_done" not in st.session_state:
    st.set_page_config(
        page_title="Nifty Strategy & Predictor Pro",
        page_icon="🔮",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    st.session_state.page_config_done = True

# ==============================
# STYLES (same as before, trimmed some unused classes)
# ==============================
st.markdown("""
    <style>
    .main { background-color: #f4f7f9; }
    .market-box {
        background-color: white;
        padding: 18px;
        border-radius: 12px;
        border: 1px solid #e1e4e8;
        box-shadow: 0px 4px 10px rgba(0,0,0,0.03);
        margin-bottom: 15px;
    }
    .entry-box {
        padding: 15px 20px;
        border-radius: 12px;
        margin-bottom: 20px;
        color: #000000;
        border-left: 6px solid;
    }
    .entry-box .status-text {
        font-weight: bold;
    }
    .greeks-panel {
        background: white;
        padding: 12px 18px;
        border-radius: 10px;
        border-left: 5px solid;
        margin-bottom: 15px;
        color: #000;
    }
    .greeks-panel .badge-pass {
        background-color: #2e7d32;
        color: white;
        padding: 2px 10px;
        border-radius: 12px;
        font-weight: bold;
        font-size: 0.8rem;
    }
    .greeks-panel .badge-weak {
        background-color: #f9a825;
        color: #000;
        padding: 2px 10px;
        border-radius: 12px;
        font-weight: bold;
        font-size: 0.8rem;
    }
    .greeks-panel .greek-item {
        display: inline-block;
        margin-right: 20px;
        font-size: 0.9rem;
    }
    .greeks-panel .greek-item b {
        color: #1a1a1a;
    }
    .indicator-pill {
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        border: 1px solid rgba(0,0,0,0.08);
        display: inline-block;
        margin-right: 6px;
    }
    .pill-green  { background:#d4edda; color:#155724; }
    .pill-red    { background:#f8d7da; color:#721c24; }
    .pill-yellow { background:#fff3cd; color:#856404; }
    .pill-gray   { background:#e9ecef; color:#495057; }
    </style>
""", unsafe_allow_html=True)

def inr_format(num):
    s = str(num)
    if len(s) <= 3:
        return s
    last_three = s[-3:]
    remaining = s[:-3]
    parts = []
    while len(remaining) > 2:
        parts.insert(0, remaining[-2:])
        remaining = remaining[:-2]
    if remaining:
        parts.insert(0, remaining)
    return ",".join(parts + [last_three])

# Auto date (today, IST) and auto weekly expiry (next Tuesday, IST)
ist_now = datetime.now(pytz.timezone("Asia/Kolkata"))
today_str = ist_now.strftime('%Y-%m-%d')

days_until_tuesday = (1 - ist_now.weekday()) % 7  # Monday=0 ... Tuesday=1
expiry_date = ist_now + dt_mod.timedelta(days=days_until_tuesday)
expiry_str = expiry_date.strftime('%Y-%m-%d')

# Sensex weekly expiry is Thursday (BSE, effective 4 Sep 2025)
days_until_thursday = (3 - ist_now.weekday()) % 7  # Monday=0 ... Thursday=3
sensex_expiry_date = ist_now + dt_mod.timedelta(days=days_until_thursday)
sensex_expiry_str = sensex_expiry_date.strftime('%Y-%m-%d')

# BankNifty expiry — monthly last Tuesday
def _last_weekday_of_month(year, month, weekday):
    """weekday: Monday=0 ... Sunday=6. Returns the last occurrence of that weekday in the given month."""
    last_day = calendar.monthrange(year, month)[1]
    d = dt_mod.date(year, month, last_day)
    offset = (d.weekday() - weekday) % 7
    return d - dt_mod.timedelta(days=offset)

_today_date = ist_now.date()
_banknifty_expiry_date = _last_weekday_of_month(_today_date.year, _today_date.month, 1)  # 1 = Tuesday
if _banknifty_expiry_date < _today_date:
    _next_month = _today_date.month + 1
    _next_year = _today_date.year
    if _next_month > 12:
        _next_month = 1
        _next_year += 1
    _banknifty_expiry_date = _last_weekday_of_month(_next_year, _next_month, 1)
banknifty_expiry_str = _banknifty_expiry_date.strftime('%Y-%m-%d')

def fetch_upstox_oi_change_data():
    url = 'https://api.upstox.com/v2/market/change-oi'
    params = {
        'instrument_key': 'NSE_INDEX|Nifty 50',
        'expiry': expiry_str,
        'date': today_str,
        'interval': 2
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': access_token
    }
    response = requests.get(url, params=params, headers=headers)
    return json.loads(response.text)

upstoxOiChangeResponse = fetch_upstox_oi_change_data()

def fetch_upstox_oi_data():
    url = 'https://api.upstox.com/v2/market/oi'
    params = {
        'instrument_key': 'NSE_INDEX|Nifty 50',
        'expiry': expiry_str,
        'date': today_str
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': access_token
    }
    response = requests.get(url, params=params, headers=headers)
    return json.loads(response.text)

upstoxOiResponse = fetch_upstox_oi_data()
data = upstoxOiResponse["data"]

def fetch_upstox_sensex_oi_change_data():
    url = 'https://api.upstox.com/v2/market/change-oi'
    params = {
        'instrument_key': 'BSE_INDEX|SENSEX',
        'expiry': sensex_expiry_str,
        'date': today_str,
        'interval': 2
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': access_token
    }
    response = requests.get(url, params=params, headers=headers)
    return json.loads(response.text)

upstoxSensexOiChangeResponse = fetch_upstox_sensex_oi_change_data()

def fetch_upstox_sensex_oi_data():
    url = 'https://api.upstox.com/v2/market/oi'
    params = {
        'instrument_key': 'BSE_INDEX|SENSEX',
        'expiry': sensex_expiry_str,
        'date': today_str
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': access_token
    }
    response = requests.get(url, params=params, headers=headers)
    return json.loads(response.text)

upstoxSensexOiResponse = fetch_upstox_sensex_oi_data()

def fetch_upstox_banknifty_oi_change_data():
    url = 'https://api.upstox.com/v2/market/change-oi'
    params = {
        'instrument_key': 'NSE_INDEX|Nifty Bank',
        'expiry': banknifty_expiry_str,
        'date': today_str,
        'interval': 2
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': access_token
    }
    response = requests.get(url, params=params, headers=headers)
    return json.loads(response.text)

upstoxBankNiftyOiChangeResponse = fetch_upstox_banknifty_oi_change_data()

def fetch_upstox_banknifty_oi_data():
    url = 'https://api.upstox.com/v2/market/oi'
    params = {
        'instrument_key': 'NSE_INDEX|Nifty Bank',
        'expiry': banknifty_expiry_str,
        'date': today_str
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': access_token
    }
    response = requests.get(url, params=params, headers=headers)
    return json.loads(response.text)

upstoxBankNiftyOiResponse = fetch_upstox_banknifty_oi_data()

# ==============================
# OPTION CHAIN + GREEKS
# ==============================
def fetch_option_chain(instrument_key, expiry_date):
    url = 'https://api.upstox.com/v2/option/chain'
    params = {
        'instrument_key': instrument_key,
        'expiry_date': expiry_date
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': access_token
    }
    response = requests.get(url, params=params, headers=headers)
    return json.loads(response.text)

def parse_greeks_by_strike(option_chain_response):
    """
    Returns { strike_price: {
        'call_delta','call_gamma','call_theta','call_vega','call_iv',
        'put_delta','put_gamma','put_theta','put_vega','put_iv'
    }}
    """
    greeks_map = {}
    if option_chain_response.get("status") != "success":
        return greeks_map
    for item in option_chain_response.get("data", []):
        strike = item.get("strike_price")
        if strike is None:
            continue
        call_g = (item.get("call_options") or {}).get("option_greeks") or {}
        put_g  = (item.get("put_options")  or {}).get("option_greeks") or {}
        greeks_map[strike] = {
            "call_delta": call_g.get("delta", 0), "call_gamma": call_g.get("gamma", 0),
            "call_theta": call_g.get("theta", 0), "call_vega":  call_g.get("vega", 0),
            "call_iv":    call_g.get("iv", 0),
            "put_delta":  put_g.get("delta", 0),  "put_gamma":  put_g.get("gamma", 0),
            "put_theta":  put_g.get("theta", 0),  "put_vega":   put_g.get("vega", 0),
            "put_iv":     put_g.get("iv", 0),
        }
    return greeks_map

def compute_greeks_confidence(entry_type, greeks):
    """
    Scores how much a strike's OI build-up actually matters to spot price,
    using Delta (relevance), Gamma (price sensitivity), Theta (decay risk), IV (context).
    Returns (confidence_0_100, delta_ok, notes_list).
    """
    if not greeks:
        return 40.0, True, ["⚪ No Greeks data — falling back to OI-only confidence"]

    notes = []
    if entry_type == "HIGH PUT":
        delta = abs(greeks.get("put_delta", 0))
        gamma = greeks.get("put_gamma", 0)
        theta = greeks.get("put_theta", 0)
        iv    = greeks.get("put_iv", 0)
    else:
        delta = abs(greeks.get("call_delta", 0))
        gamma = greeks.get("call_gamma", 0)
        theta = greeks.get("call_theta", 0)
        iv    = greeks.get("call_iv", 0)

    # Too near 0 delta = strike is too far OTM to matter; too near 1 = deep ITM, already priced in.
    delta_ok = 0.15 <= delta <= 0.75
    notes.append(f"{'✅' if delta_ok else '⚠️'} Delta {delta:.2f} {'in' if delta_ok else 'outside'} relevant band (0.15–0.75)")

    delta_score = max(0, 100 - abs(delta - 0.45) * 150)   # peaks near 0.45 delta (slightly OTM, high-OI zone)
    gamma_score = min(100, gamma * 5000)                    # gamma is typically 0.0005–0.02, scale up
    theta_penalty = min(30, max(0, -theta))                 # steep decay trims confidence a bit

    if theta < -5:
        notes.append(f"🔥 Theta {theta:.2f}/day — fast premium decay if trading the option itself")
    if iv:
        notes.append(f"📈 IV: {iv:.1f}%")

    confidence = round(max(0, min(100, 0.55 * delta_score + 0.35 * gamma_score - 0.10 * theta_penalty)), 1)
    return confidence, delta_ok, notes

nifty_option_chain_response = fetch_option_chain('NSE_INDEX|Nifty 50', expiry_str)
nifty_greeks_by_strike = parse_greeks_by_strike(nifty_option_chain_response)

sensex_option_chain_response = fetch_option_chain('BSE_INDEX|SENSEX', sensex_expiry_str)
sensex_greeks_by_strike = parse_greeks_by_strike(sensex_option_chain_response)

banknifty_option_chain_response = fetch_option_chain('NSE_INDEX|Nifty Bank', banknifty_expiry_str)
banknifty_greeks_by_strike = parse_greeks_by_strike(banknifty_option_chain_response)

def reusable_display_oi_data(upstoxResponse, title):
    data = upstoxResponse["data"]
    Total_Puts = 0
    Total_Calls = 0

    def get_oi_value(item, key1, key2, format_num=0):
        value = item.get(key1) if item.get(key1) is not None else item.get(key2)
        return inr_format(value) if format_num else value

    def get_high_oi(item):
        nonlocal Total_Calls, Total_Puts
        if get_oi_value(item, 'put_oi', 'put_change_oi') > get_oi_value(item, 'call_oi', 'call_change_oi'):
            Total_Puts += 1
            return "HIGH PUT"
        else:
            Total_Calls += 1
            return "HIGH CALL"

    oi_rows = [
        {
            "Strike Price": int(item["strike_price"]),
            "Call OI": get_oi_value(item, 'call_oi', 'call_change_oi', format_num=1),
            "Put OI": get_oi_value(item, 'put_oi', 'put_change_oi', format_num=1),
            "HIGH OI": get_high_oi(item),
            "OI Difference": abs(get_oi_value(item, 'put_oi', 'put_change_oi') - get_oi_value(item, 'call_oi', 'call_change_oi')),
        }
        for item in data["call_put_oi_data_list"]
    ]

    oi_header = [{
        "Status": upstoxResponse["status"],
        "Total Puts": get_oi_value(data, 'total_puts', 'total_put_change_oi', format_num=1),
        "Total Calls": get_oi_value(data, 'total_calls', 'total_call_change_oi', format_num=1),
        "Spot Closing Price": data.get('spot_closing_price'),
        "Expiry": data.get('expiry'),
        "Total Call OI": Total_Calls,
        "Total Put OI": Total_Puts
    }]

    st.subheader(title)
    st.dataframe(pd.DataFrame(oi_header))

    top_20 = pd.DataFrame(oi_rows).sort_values(
        by="OI Difference", ascending=False
    ).head(20).reset_index(drop=True)

    def highlight_top5(row):
        if row.name < 5:
            return ["background-color: #ffd700; font-weight: bold; color: #000000;"] * len(row)
        return [""] * len(row)

    st.dataframe(top_20.style.apply(highlight_top5, axis=1))

# ==============================
# GLOBAL CONFIG & TIMING
# ==============================
st_autorefresh(interval=15_000, key="global_sync_refresh")
ist = pytz.timezone("Asia/Kolkata")
now = datetime.now(ist)
today = now.strftime("%Y-%m-%d")

# ==============================
# SIDEBAR (only index selection)
# ==============================
with st.sidebar:
    st.title("🎯 Select Index")
    st.sidebar.markdown(f"### 🕒 IST: {now.strftime('%H:%M:%S')}")

    index_selection = st.radio(
        "Select Index",
        ["Nifty", "Sensex", "BankNifty"],
        index=0,
        help="Switch between Nifty, Sensex, and BankNifty data views."
    )

# ==============================
# FETCH PRICES FOR NIFTY, SENSEX, BANKNIFTY (only these three)
# ==============================
TV_URL  = "https://scanner.tradingview.com/global/scan"
HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
SESSION = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504]
)
adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)

# Minimal instrument list – only the three Indian indices
minimal_symbols = [
    {"name": "NIFTY 50",   "tv_symbol": "NSE:NIFTY"},
    {"name": "SENSEX",     "tv_symbol": "BSE:SENSEX"},
    {"name": "BANK NIFTY", "tv_symbol": "NSE:BANKNIFTY"},
]

def fetch_price(symbol_dict):
    payload = {
        "symbols": {"tickers": [symbol_dict["tv_symbol"]], "query": {"types": []}},
        "columns": ["close", "change", "change_abs"]
    }
    try:
        r = SESSION.post(TV_URL, json=payload, headers=HEADERS, timeout=5)
        r.raise_for_status()
        d = r.json()["data"][0]["d"]
        close, pct, change_abs = d[0], d[1], d[2]
        prev_close = close - change_abs
        return symbol_dict, (round(prev_close, 2), round(close, 2), round(change_abs, 2), round(pct, 2))
    except Exception as e:
        print(f"Error fetching {symbol_dict['name']}: {e}")
        return symbol_dict, None

with ThreadPoolExecutor(max_workers=len(minimal_symbols)) as executor:
    price_results = list(executor.map(fetch_price, minimal_symbols))

# Parse prices
nifty_price = nifty_prev_close = 0.0
sensex_price = sensex_prev_close = 0.0
banknifty_price = banknifty_prev_close = 0.0

for s, res in price_results:
    if res:
        prev, close, change, pct = res
        if s["name"] == "NIFTY 50":
            nifty_price, nifty_prev_close = close, prev
        elif s["name"] == "SENSEX":
            sensex_price, sensex_prev_close = close, prev
        elif s["name"] == "BANK NIFTY":
            banknifty_price, banknifty_prev_close = close, prev

# ==============================
# OI FLOW FETCHING & PARSING
# ==============================
def fetch_futures_data():
    url = 'https://api.upstox.com/v2/market/smartlist/futures'
    params = {
        'asset_type': 'INDEX',
        'category': 'TOP_TRADED',
        'page_number': 1,
        'page_size': 20,
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': access_token
    }
    response = requests.get(url, params=params, headers=headers)
    return json.loads(response.text)

def parse_futures_flow(data, title="OI Flow Details", key_prefix=None, key_contains=None):
    smartlist = data['data']['smartlist']
    if key_prefix:
        smartlist = [item for item in smartlist if item["instrument_key"].startswith(key_prefix)]
    if key_contains:
        smartlist = [item for item in smartlist if key_contains in item["instrument_key"]]
    rows = []
    weighted_score = 0.0
    total_value_weight = 0.0
    for item in smartlist:
        current_value = item['metric']['current']
        if current_value < 100_000_000:  # Ignore tiny turnover
            continue
        price_change = item['price']['change_pct']
        change_abs = item['metric']['change_abs']
        change_pct = item['metric']['change_pct']
        score = 0.0
        if change_abs > 1_000_000_000 and price_change < -0.3:
            score = -0.9
        elif change_abs > 1_000_000_000 and price_change > 0.3:
            score = 0.9
        elif change_pct > 30 and price_change < -0.3:
            score = -0.6
        elif change_pct > 10 and price_change < -0.5:
            score = -0.4
        elif change_pct > 10 and price_change > 0.5:
            score = 0.4
        weight = current_value / 1_000_000_000
        weighted_score += score * weight
        total_value_weight += weight
        rows.append({
            "instrument_key": item["instrument_key"],
            "score": score,
            "weight": weight,
            "current_value": current_value,
            "price_change": price_change,
            "change_abs": change_abs,
            "change_pct": change_pct
        })
    if total_value_weight == 0:
        final_score = 0.0
    else:
        final_score = weighted_score / total_value_weight
    final_score = max(-1, min(1, final_score))
    return {
        "score": final_score,
        "rows": rows,
        "title": title,
        "key_prefix": key_prefix
    }

fetched_data = fetch_futures_data()
nifty_flow_result = parse_futures_flow(fetched_data, title="Nifty OI Flow Details", key_prefix="NSE_FO")
sensex_flow_result = parse_futures_flow(fetched_data, title="Sensex OI Flow Details", key_prefix="BSE_FO")
banknifty_flow_result = parse_futures_flow(fetched_data, title="BankNifty OI Flow Details", key_prefix="NSE_FO", key_contains="BANKNIFTY")

# ==============================
# Code 1 / 5 / 6 – Entry/Exit Signals (unchanged)
# ==============================
def get_entry_signal_from_change_oi(change_oi_response, spot_price, buffer_points=27, greeks_by_strike=None, max_candidates=5):
    if not change_oi_response or change_oi_response.get("status") != "success":
        return None
    data = change_oi_response.get("data") or {}
    items = data.get("call_put_oi_data_list") or []
    if not items:
        return None

    ranked = []
    for item in items:
        call_oi = item.get("call_change_oi", item.get("call_oi", 0))
        put_oi = item.get("put_change_oi", item.get("put_oi", 0))
        ranked.append((abs(put_oi - call_oi), item, call_oi, put_oi))
    ranked.sort(key=lambda x: x[0], reverse=True)

    best_item = None
    best_diff = -1
    best_call_oi = best_put_oi = 0
    best_conf, best_delta_ok, best_notes = 40.0, True, []

    for diff, item, call_oi, put_oi in ranked[:max_candidates]:
        high_type = "HIGH PUT" if put_oi > call_oi else "HIGH CALL"
        strike = item["strike_price"]
        greeks = greeks_by_strike.get(strike) if greeks_by_strike else None
        conf, delta_ok, notes = compute_greeks_confidence(high_type, greeks)
        if delta_ok:
            best_item, best_diff = item, diff
            best_call_oi, best_put_oi = call_oi, put_oi
            best_conf, best_delta_ok, best_notes = conf, delta_ok, notes
            break
        elif best_item is None:
            best_item, best_diff = item, diff
            best_call_oi, best_put_oi = call_oi, put_oi
            best_conf, best_delta_ok, best_notes = conf, delta_ok, notes

    if best_item is None:
        return None

    strike = best_item["strike_price"]
    high_type = "HIGH PUT" if best_put_oi > best_call_oi else "HIGH CALL"

    if high_type == "HIGH PUT":
        trigger_price = strike + buffer_points
        signal = "BUY"
        reason = f"Support at {strike} (Put OI > Call OI). Trigger at {trigger_price}"
    else:
        trigger_price = strike - buffer_points
        signal = "SELL"
        reason = f"Resistance at {strike} (Call OI > Put OI). Trigger at {trigger_price}"

    active = False
    if signal == "BUY" and spot_price >= trigger_price:
        active = True
    elif signal == "SELL" and spot_price <= trigger_price:
        active = True

    return {
        "strike": strike,
        "high_type": high_type,
        "signal": signal,
        "trigger_price": trigger_price,
        "active": active,
        "reason": reason,
        "call_oi": best_call_oi,
        "put_oi": best_put_oi,
        "oi_diff": best_diff,
        "greeks": greeks_by_strike.get(strike) if greeks_by_strike else None,
        "greeks_confidence": best_conf,
        "delta_ok": best_delta_ok,
        "greeks_notes": best_notes,
    }

def get_exit_signal_from_change_oi(change_oi_response, spot_price, entry_signal, buffer_points=27, min_gap=100, greeks_by_strike=None):
    if not change_oi_response or change_oi_response.get("status") != "success":
        return None
    data = change_oi_response.get("data") or {}
    items = data.get("call_put_oi_data_list") or []
    if not items:
        return None

    if entry_signal["signal"] == "BUY":
        opposite_high_type = "HIGH CALL"
    else:
        opposite_high_type = "HIGH PUT"

    best_item = None
    best_diff = -1
    for item in items:
        call_oi = item.get("call_change_oi", item.get("call_oi", 0))
        put_oi = item.get("put_change_oi", item.get("put_oi", 0))
        high_type = "HIGH PUT" if put_oi > call_oi else "HIGH CALL"
        if high_type == opposite_high_type:
            diff = abs(put_oi - call_oi)
            if diff > best_diff:
                best_diff = diff
                best_item = item

    if best_item is None:
        return None

    strike = best_item["strike_price"]
    call_oi = best_item.get("call_change_oi", best_item.get("call_oi", 0))
    put_oi = best_item.get("put_change_oi", best_item.get("put_oi", 0))

    if opposite_high_type == "HIGH PUT":
        trigger_price = strike + buffer_points
        exit_signal_type = "BUY"
    else:
        trigger_price = strike - buffer_points
        exit_signal_type = "SELL"

    entry_trigger = entry_signal["trigger_price"]
    if abs(entry_trigger - trigger_price) < min_gap:
        return None

    active = False
    if exit_signal_type == "BUY" and spot_price >= trigger_price:
        active = True
    elif exit_signal_type == "SELL" and spot_price <= trigger_price:
        active = True

    if opposite_high_type == "HIGH PUT":
        reason = f"Exit BUY signal: Support at {strike} (Put OI > Call OI). Trigger at {trigger_price}"
    else:
        reason = f"Exit SELL signal: Resistance at {strike} (Call OI > Put OI). Trigger at {trigger_price}"

    return {
        "strike": strike,
        "high_type": opposite_high_type,
        "signal": exit_signal_type,
        "trigger_price": trigger_price,
        "active": active,
        "reason": reason,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "oi_diff": best_diff,
        "greeks": greeks_by_strike.get(strike) if greeks_by_strike else None,
    }

def render_greeks_panel(signal_data, label):
    if not signal_data or not signal_data.get("greeks"):
        st.caption(f"ℹ️ No Greeks data for {label} key strike.")
        return
    g = signal_data["greeks"]
    high_type = signal_data["high_type"]
    conf = signal_data.get("greeks_confidence", 0)
    if high_type == "HIGH PUT":
        delta, gamma, theta, vega, iv, leg = g["put_delta"], g["put_gamma"], g["put_theta"], g["put_vega"], g["put_iv"], "PUT"
    else:
        delta, gamma, theta, vega, iv, leg = g["call_delta"], g["call_gamma"], g["call_theta"], g["call_vega"], g["call_iv"], "CALL"

    color = "#2e7d32" if conf >= 60 else "#f9a825" if conf >= 35 else "#c62828"
    badge_class = "badge-pass" if signal_data.get("delta_ok", True) else "badge-weak"
    badge_text = "✅ PASSES DELTA FILTER" if signal_data.get("delta_ok", True) else "⚠️ WEAK — OUTSIDE DELTA BAND"

    st.markdown(f"""
    <div class="greeks-panel" style="border-left-color: {color};">
        <b>{leg} Greeks @ {signal_data['strike']}</b> &nbsp;|&nbsp; <span class="{badge_class}">{badge_text}</span>
        <div style="display:flex; gap:20px; margin-top:6px; font-size:0.9rem; flex-wrap:wrap;">
            <span class="greek-item">Δ Delta: <b>{delta:.3f}</b></span>
            <span class="greek-item">Γ Gamma: <b>{gamma:.5f}</b></span>
            <span class="greek-item">Θ Theta: <b>{theta:.2f}</b></span>
            <span class="greek-item">V Vega: <b>{vega:.2f}</b></span>
            <span class="greek-item">IV: <b>{iv:.1f}%</b></span>
            <span class="greek-item">Greeks Confidence: <b>{conf:.0f}%</b></span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    for n in signal_data.get("greeks_notes", []):
        st.caption(n)

# ==============================
# COMPUTE SIGNALS
# ==============================
entry_datetime = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")

# NIFTY signals (Code 1)
nifty_entry_signal = None
if nifty_price > 0 and upstoxOiChangeResponse.get("status") == "success":
    nifty_entry_signal = get_entry_signal_from_change_oi(upstoxOiChangeResponse, nifty_price, buffer_points=27, greeks_by_strike=nifty_greeks_by_strike)

nifty_exit_signal = None
if nifty_entry_signal:
    nifty_exit_signal = get_exit_signal_from_change_oi(upstoxOiChangeResponse, nifty_price, nifty_entry_signal, buffer_points=27, min_gap=100, greeks_by_strike=nifty_greeks_by_strike)
    if nifty_exit_signal is None:
        nifty_entry_signal = None

# SENSEX signals (Code 5)
sensex_entry_signal = None
if sensex_price > 0 and upstoxSensexOiChangeResponse.get("status") == "success":
    sensex_entry_signal = get_entry_signal_from_change_oi(upstoxSensexOiChangeResponse, sensex_price, buffer_points=27, greeks_by_strike=sensex_greeks_by_strike)

sensex_exit_signal = None
if sensex_entry_signal:
    sensex_exit_signal = get_exit_signal_from_change_oi(upstoxSensexOiChangeResponse, sensex_price, sensex_entry_signal, buffer_points=27, min_gap=100, greeks_by_strike=sensex_greeks_by_strike)
    if sensex_exit_signal is None:
        sensex_entry_signal = None

# BANKNIFTY signals (Code 6)
banknifty_entry_signal = None
if banknifty_price > 0 and upstoxBankNiftyOiChangeResponse.get("status") == "success":
    banknifty_entry_signal = get_entry_signal_from_change_oi(upstoxBankNiftyOiChangeResponse, banknifty_price, buffer_points=27, greeks_by_strike=banknifty_greeks_by_strike)

banknifty_exit_signal = None
if banknifty_entry_signal:
    banknifty_exit_signal = get_exit_signal_from_change_oi(upstoxBankNiftyOiChangeResponse, banknifty_price, banknifty_entry_signal, buffer_points=27, min_gap=100, greeks_by_strike=banknifty_greeks_by_strike)
    if banknifty_exit_signal is None:
        banknifty_entry_signal = None

# ==============================
# UI RENDER
# ==============================
if index_selection == "Nifty":
    st.title("🔮 Nifty Analytics & Strategy Suite — Pro")
elif index_selection == "Sensex":
    st.title("🔮 Sensex Analytics & Strategy Suite — Pro")
else:
    st.title("🔮 BankNifty Analytics & Strategy Suite — Pro")

# ==============================
# NIFTY VIEW
# ==============================
if index_selection == "Nifty":
    # ---- Code 1: Nifty OI Change Entry Signal ----
    st.subheader("📊 Code 1 — Nifty OI Change Entry Signal")
    if nifty_entry_signal:
        signal = nifty_entry_signal["signal"]
        active = nifty_entry_signal["active"]
        emoji = "🟢" if signal == "BUY" else "🔴"
        status_text = "ACTIVE" if active else "PENDING (waiting for price to cross trigger)"
        bg_color = "#2e7d32" if active and signal == "BUY" else ("#c62828" if active and signal == "SELL" else "#f9a825")
        text_color = "white" if active else "black"
        border_color = "#2e7d32" if signal == "BUY" else "#c62828"
        st.markdown(f"""
        <div class="entry-box" style="background: {bg_color}; border-left-color: {border_color}; color: {text_color};">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                <div>
                    <span style="font-size: 1.8rem; font-weight: 800;">{emoji} {signal} ENTRY</span>
                    <span style="margin-left: 15px; font-size: 1.2rem;">at {nifty_entry_signal['trigger_price']:,.2f}</span>
                    <span style="margin-left: 15px; background: rgba(0,0,0,0.15); padding: 2px 10px; border-radius: 20px;">{nifty_entry_signal['high_type']}</span>
                </div>
                <div style="font-weight: bold;">
                    <span class="status-text" style="background: rgba(0,0,0,0.3); padding: 2px 10px; border-radius: 8px;">{status_text}</span>
                    <span style="margin-left: 20px; font-size: 0.9rem;">Entry Time: {entry_datetime}</span>
                </div>
            </div>
            <div style="margin-top: 8px; font-size: 0.95rem; opacity: 0.9;">
                <span>📊 Current Nifty: <b>{nifty_price:,.2f}</b> &nbsp;|&nbsp; Key Strike: <b>{nifty_entry_signal['strike']}</b> &nbsp;|&nbsp; OI Diff: <b>{nifty_entry_signal['oi_diff']:,.0f}</b></span>
                <span style="margin-left: 20px;">📌 {nifty_entry_signal['reason']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        render_greeks_panel(nifty_entry_signal, "Nifty Entry")
    else:
        st.info("ℹ️ No Nifty Change OI entry signal (gap < 100 pts or no opposite OI).")

    # ---- Code 1: Nifty OI Change Exit Signal ----
    st.subheader("📊 Code 1 — Nifty OI Change Exit Signal")
    if nifty_exit_signal:
        signal = nifty_exit_signal["signal"]
        active = nifty_exit_signal["active"]
        emoji = "🟢" if signal == "BUY" else "🔴"
        status_text = "EXIT ACTIVE" if active else "PENDING (waiting for price to cross trigger)"
        bg_color = "#2e7d32" if active and signal=="BUY" else ("#c62828" if active and signal=="SELL" else "#f9a825")
        text_color = "white" if active else "black"
        border_color = "#0277bd" if signal=="BUY" else "#d84315"
        st.markdown(f"""
        <div class="entry-box" style="background: {bg_color}; border-left-color: {border_color}; color: {text_color};">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                <div>
                    <span style="font-size: 1.8rem; font-weight: 800;">{emoji} EXIT ({'BUY to cover' if signal=='BUY' else 'SELL to close'})</span>
                    <span style="margin-left: 15px; font-size: 1.2rem;">at {nifty_exit_signal['trigger_price']:,.2f}</span>
                    <span style="margin-left: 15px; background: rgba(0,0,0,0.15); padding: 2px 10px; border-radius: 20px;">{nifty_exit_signal['high_type']}</span>
                </div>
                <div style="font-weight: bold;">
                    <span class="status-text" style="background: rgba(0,0,0,0.3); padding: 2px 10px; border-radius: 8px;">{status_text}</span>
                    <span style="margin-left: 20px; font-size: 0.9rem;">Exit Time: {entry_datetime}</span>
                </div>
            </div>
            <div style="margin-top: 8px; font-size: 0.95rem; opacity: 0.9;">
                <span>📊 Current Nifty: <b>{nifty_price:,.2f}</b> &nbsp;|&nbsp; Key Strike: <b>{nifty_exit_signal['strike']}</b> &nbsp;|&nbsp; OI Diff: <b>{nifty_exit_signal['oi_diff']:,.0f}</b></span>
                <span style="margin-left: 20px;">📌 {nifty_exit_signal['reason']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        render_greeks_panel(nifty_exit_signal, "Nifty Exit")
    else:
        st.info("ℹ️ No Nifty exit signal available (opposite OI build‑up not found or gap < 100 pts).")

    # ---- Nifty OI Data ----
    reusable_display_oi_data(upstoxOiResponse, "Nifty Open Interest Data")
    reusable_display_oi_data(upstoxOiChangeResponse, "Nifty Change in OI")

    # ---- Nifty OI Flow ----
    if nifty_flow_result["rows"]:
        st.subheader(f"{nifty_flow_result['title']} — Macro Score: {nifty_flow_result['score']:.2f}")
        st.markdown("**Weighted Macro Score (-1 to +1)**: Based on absolute turnover and price change across top traded futures.")
        indicator = "Bullish" if nifty_flow_result["score"] > 0 else ("Bearish" if nifty_flow_result["score"] < 0 else "Sideways")
        st.write(f"Market Bias: {indicator}")
        st.dataframe(pd.DataFrame(nifty_flow_result["rows"]))
    else:
        st.info("No Nifty futures met the turnover threshold right now.")

# ==============================
# SENSEX VIEW
# ==============================
elif index_selection == "Sensex":
    st.subheader("📊 Code 5 — Sensex OI Change Entry Signal")
    if sensex_entry_signal:
        signal = sensex_entry_signal["signal"]
        active = sensex_entry_signal["active"]
        emoji = "🟢" if signal == "BUY" else "🔴"
        status_text = "ACTIVE" if active else "PENDING (waiting for price to cross trigger)"
        bg_color = "#2e7d32" if active and signal=="BUY" else ("#c62828" if active and signal=="SELL" else "#f9a825")
        text_color = "white" if active else "black"
        border_color = "#2e7d32" if signal=="BUY" else "#c62828"
        st.markdown(f"""
        <div class="entry-box" style="background: {bg_color}; border-left-color: {border_color}; color: {text_color};">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                <div>
                    <span style="font-size: 1.8rem; font-weight: 800;">{emoji} {signal} ENTRY</span>
                    <span style="margin-left: 15px; font-size: 1.2rem;">at {sensex_entry_signal['trigger_price']:,.2f}</span>
                    <span style="margin-left: 15px; background: rgba(0,0,0,0.15); padding: 2px 10px; border-radius: 20px;">{sensex_entry_signal['high_type']}</span>
                </div>
                <div style="font-weight: bold;">
                    <span class="status-text" style="background: rgba(0,0,0,0.3); padding: 2px 10px; border-radius: 8px;">{status_text}</span>
                    <span style="margin-left: 20px; font-size: 0.9rem;">Entry Time: {entry_datetime}</span>
                </div>
            </div>
            <div style="margin-top: 8px; font-size: 0.95rem; opacity: 0.9;">
                <span>📊 Current Sensex: <b>{sensex_price:,.2f}</b> &nbsp;|&nbsp; Key Strike: <b>{sensex_entry_signal['strike']}</b> &nbsp;|&nbsp; OI Diff: <b>{sensex_entry_signal['oi_diff']:,.0f}</b></span>
                <span style="margin-left: 20px;">📌 {sensex_entry_signal['reason']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        render_greeks_panel(sensex_entry_signal, "Sensex Entry")
    else:
        st.info("ℹ️ No Sensex Change OI entry signal (gap < 100 pts or no opposite OI).")

    st.subheader("📊 Code 5 — Sensex OI Change Exit Signal")
    if sensex_exit_signal:
        signal = sensex_exit_signal["signal"]
        active = sensex_exit_signal["active"]
        emoji = "🟢" if signal == "BUY" else "🔴"
        status_text = "EXIT ACTIVE" if active else "PENDING (waiting for price to cross trigger)"
        bg_color = "#2e7d32" if active and signal=="BUY" else ("#c62828" if active and signal=="SELL" else "#f9a825")
        text_color = "white" if active else "black"
        border_color = "#0277bd" if signal=="BUY" else "#d84315"
        st.markdown(f"""
        <div class="entry-box" style="background: {bg_color}; border-left-color: {border_color}; color: {text_color};">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                <div>
                    <span style="font-size: 1.8rem; font-weight: 800;">{emoji} EXIT ({'BUY to cover' if signal=='BUY' else 'SELL to close'})</span>
                    <span style="margin-left: 15px; font-size: 1.2rem;">at {sensex_exit_signal['trigger_price']:,.2f}</span>
                    <span style="margin-left: 15px; background: rgba(0,0,0,0.15); padding: 2px 10px; border-radius: 20px;">{sensex_exit_signal['high_type']}</span>
                </div>
                <div style="font-weight: bold;">
                    <span class="status-text" style="background: rgba(0,0,0,0.3); padding: 2px 10px; border-radius: 8px;">{status_text}</span>
                    <span style="margin-left: 20px; font-size: 0.9rem;">Exit Time: {entry_datetime}</span>
                </div>
            </div>
            <div style="margin-top: 8px; font-size: 0.95rem; opacity: 0.9;">
                <span>📊 Current Sensex: <b>{sensex_price:,.2f}</b> &nbsp;|&nbsp; Key Strike: <b>{sensex_exit_signal['strike']}</b> &nbsp;|&nbsp; OI Diff: <b>{sensex_exit_signal['oi_diff']:,.0f}</b></span>
                <span style="margin-left: 20px;">📌 {sensex_exit_signal['reason']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        render_greeks_panel(sensex_exit_signal, "Sensex Exit")
    else:
        st.info("ℹ️ No Sensex exit signal available (opposite OI build‑up not found or gap < 100 pts).")

    reusable_display_oi_data(upstoxSensexOiResponse, "Sensex Open Interest Data")
    reusable_display_oi_data(upstoxSensexOiChangeResponse, "Sensex Change in OI")

    if sensex_flow_result["rows"]:
        st.subheader(f"{sensex_flow_result['title']} — Macro Score: {sensex_flow_result['score']:.2f}")
        st.markdown("**Weighted Macro Score (-1 to +1)**: Based on absolute turnover and price change across top traded futures.")
        indicator = "Bullish" if sensex_flow_result["score"] > 0 else ("Bearish" if sensex_flow_result["score"] < 0 else "Sideways")
        st.write(f"Market Bias: {indicator}")
        st.dataframe(pd.DataFrame(sensex_flow_result["rows"]))
    else:
        st.info("No Sensex futures met the turnover threshold right now.")

# ==============================
# BANKNIFTY VIEW
# ==============================
elif index_selection == "BankNifty":
    st.subheader("📊 Code 6 — BankNifty OI Change Entry Signal")
    if banknifty_entry_signal:
        signal = banknifty_entry_signal["signal"]
        active = banknifty_entry_signal["active"]
        emoji = "🟢" if signal == "BUY" else "🔴"
        status_text = "ACTIVE" if active else "PENDING (waiting for price to cross trigger)"
        bg_color = "#2e7d32" if active and signal=="BUY" else ("#c62828" if active and signal=="SELL" else "#f9a825")
        text_color = "white" if active else "black"
        border_color = "#2e7d32" if signal=="BUY" else "#c62828"
        st.markdown(f"""
        <div class="entry-box" style="background: {bg_color}; border-left-color: {border_color}; color: {text_color};">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                <div>
                    <span style="font-size: 1.8rem; font-weight: 800;">{emoji} {signal} ENTRY</span>
                    <span style="margin-left: 15px; font-size: 1.2rem;">at {banknifty_entry_signal['trigger_price']:,.2f}</span>
                    <span style="margin-left: 15px; background: rgba(0,0,0,0.15); padding: 2px 10px; border-radius: 20px;">{banknifty_entry_signal['high_type']}</span>
                </div>
                <div style="font-weight: bold;">
                    <span class="status-text" style="background: rgba(0,0,0,0.3); padding: 2px 10px; border-radius: 8px;">{status_text}</span>
                    <span style="margin-left: 20px; font-size: 0.9rem;">Entry Time: {entry_datetime}</span>
                </div>
            </div>
            <div style="margin-top: 8px; font-size: 0.95rem; opacity: 0.9;">
                <span>📊 Current BankNifty: <b>{banknifty_price:,.2f}</b> &nbsp;|&nbsp; Key Strike: <b>{banknifty_entry_signal['strike']}</b> &nbsp;|&nbsp; OI Diff: <b>{banknifty_entry_signal['oi_diff']:,.0f}</b></span>
                <span style="margin-left: 20px;">📌 {banknifty_entry_signal['reason']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        render_greeks_panel(banknifty_entry_signal, "BankNifty Entry")
    else:
        st.info("ℹ️ No BankNifty Change OI entry signal (gap < 100 pts or no opposite OI).")

    st.subheader("📊 Code 6 — BankNifty OI Change Exit Signal")
    if banknifty_exit_signal:
        signal = banknifty_exit_signal["signal"]
        active = banknifty_exit_signal["active"]
        emoji = "🟢" if signal == "BUY" else "🔴"
        status_text = "EXIT ACTIVE" if active else "PENDING (waiting for price to cross trigger)"
        bg_color = "#2e7d32" if active and signal=="BUY" else ("#c62828" if active and signal=="SELL" else "#f9a825")
        text_color = "white" if active else "black"
        border_color = "#0277bd" if signal=="BUY" else "#d84315"
        st.markdown(f"""
        <div class="entry-box" style="background: {bg_color}; border-left-color: {border_color}; color: {text_color};">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                <div>
                    <span style="font-size: 1.8rem; font-weight: 800;">{emoji} EXIT ({'BUY to cover' if signal=='BUY' else 'SELL to close'})</span>
                    <span style="margin-left: 15px; font-size: 1.2rem;">at {banknifty_exit_signal['trigger_price']:,.2f}</span>
                    <span style="margin-left: 15px; background: rgba(0,0,0,0.15); padding: 2px 10px; border-radius: 20px;">{banknifty_exit_signal['high_type']}</span>
                </div>
                <div style="font-weight: bold;">
                    <span class="status-text" style="background: rgba(0,0,0,0.3); padding: 2px 10px; border-radius: 8px;">{status_text}</span>
                    <span style="margin-left: 20px; font-size: 0.9rem;">Exit Time: {entry_datetime}</span>
                </div>
            </div>
            <div style="margin-top: 8px; font-size: 0.95rem; opacity: 0.9;">
                <span>📊 Current BankNifty: <b>{banknifty_price:,.2f}</b> &nbsp;|&nbsp; Key Strike: <b>{banknifty_exit_signal['strike']}</b> &nbsp;|&nbsp; OI Diff: <b>{banknifty_exit_signal['oi_diff']:,.0f}</b></span>
                <span style="margin-left: 20px;">📌 {banknifty_exit_signal['reason']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        render_greeks_panel(banknifty_exit_signal, "BankNifty Exit")
    else:
        st.info("ℹ️ No BankNifty exit signal available (opposite OI build‑up not found or gap < 100 pts).")

    reusable_display_oi_data(upstoxBankNiftyOiResponse, "BankNifty Open Interest Data")
    reusable_display_oi_data(upstoxBankNiftyOiChangeResponse, "BankNifty Change in OI")

    if banknifty_flow_result["rows"]:
        st.subheader(f"{banknifty_flow_result['title']} — Macro Score: {banknifty_flow_result['score']:.2f}")
        st.markdown("**Weighted Macro Score (-1 to +1)**: Based on absolute turnover and price change across top traded futures.")
        indicator = "Bullish" if banknifty_flow_result["score"] > 0 else ("Bearish" if banknifty_flow_result["score"] < 0 else "Sideways")
        st.write(f"Market Bias: {indicator}")
        st.dataframe(pd.DataFrame(banknifty_flow_result["rows"]))
    else:
        st.info("No BankNifty futures met the turnover threshold right now.")
