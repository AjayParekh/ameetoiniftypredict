"""
nifty_smc_chart.py — Standalone Nifty Chart + Smart Money Concepts + Pure Change-in-OI Meter.

Merge mode
----------
Add to your existing streamlit_app.py (only 3 lines):

    from nifty_smc_chart import render_nifty_price_bar, render_smc_section
    render_nifty_price_bar()            # after st.title(...)
    render_smc_section(expiry_str)      # after reversal meter block

Standalone
----------
    streamlit run nifty_smc_chart.py
"""

import streamlit as st
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import json
from urllib.parse import quote

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False


# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #
ACCESS_TOKEN = (
    "Bearer eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ."
    "eyJzdWIiOiIxMDM2NjciLCJqdGkiOiI2OWQyMzJlMWNjZDUyZDRjZDQzMzc5NjYiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlzRXh0ZW5kZWQiOnRydWUsImlhdCI6MTc3NTM4MzI2NSwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxODA2OTYyNDAwfQ."
    "VFRZ5NP87NM1Vyn4-bCB2FAvanu4wsueNHo_POQtPv8"
)

NIFTY_KEY = "NSE_INDEX|Nifty 50"
IST = pytz.timezone("Asia/Kolkata")

TIMEFRAMES = {
    "1 min":  ("minutes", "1"),
    "3 min":  ("minutes", "3"),
    "5 min":  ("minutes", "5"),
    "15 min": ("minutes", "15"),
    "30 min": ("minutes", "30"),
    "1 hour": ("hours",   "1"),
    "Daily":  ("days",    "1"),
}

HEADERS = {"Accept": "application/json", "Authorization": ACCESS_TOKEN}


# ------------------------------------------------------------------ #
# Data fetching
# ------------------------------------------------------------------ #
def _enc(key: str) -> str:
    return quote(key, safe="")


@st.cache_data(ttl=10, show_spinner=False)
def _fetch_nifty_quote():
    """Last price, absolute change, % change and previous close for Nifty Spot."""
    try:
        r = requests.get(
            "https://api.upstox.com/v2/market-quote/quotes",
            params={"instrument_key": NIFTY_KEY},
            headers=HEADERS, timeout=5,
        )
        d = r.json()
        if d.get("status") != "success":
            return None
        for _, v in (d.get("data") or {}).items():
            lp = v.get("last_price")
            if not lp:
                continue
            net = v.get("net_change")
            prev = (v.get("ohlc") or {}).get("close")
            if net is None and prev:
                net = float(lp) - float(prev)
            if prev is None and net is not None:
                prev = float(lp) - float(net)
            pct = (float(net) / float(prev) * 100) if (net is not None and prev) else 0.0
            return {
                "last": float(lp),
                "change": float(net or 0),
                "pct": float(pct),
                "prev_close": float(prev or 0),
            }
    except Exception as e:
        print(f"nifty quote error: {e}")
    return None


@st.cache_data(ttl=20, show_spinner=False)
def _fetch_intraday_v3(inst_key: str, unit: str, interval: str):
    url = f"https://api.upstox.com/v3/historical-candle/intraday/{_enc(inst_key)}/{unit}/{interval}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        d = r.json()
        if d.get("status") != "success":
            return None
        return (d.get("data") or {}).get("candles") or []
    except Exception as e:
        print(f"intraday fetch error: {e}")
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_historical_v3(inst_key: str, unit: str, interval: str, to_date: str, from_date: str):
    url = (
        f"https://api.upstox.com/v3/historical-candle/"
        f"{_enc(inst_key)}/{unit}/{interval}/{to_date}/{from_date}"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        d = r.json()
        if d.get("status") != "success":
            return None
        return (d.get("data") or {}).get("candles") or []
    except Exception as e:
        print(f"historical fetch error: {e}")
        return None


@st.cache_data(ttl=15, show_spinner=False)
def _fetch_change_oi(inst_key: str, expiry: str, date: str):
    url = "https://api.upstox.com/v2/market/change-oi"
    params = {"instrument_key": inst_key, "expiry": expiry, "date": date, "interval": 2}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=8)
        return r.json()
    except Exception as e:
        print(f"change-oi fetch error: {e}")
        return None


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_nearest_expiry(inst_key: str, today_key: str):
    try:
        r = requests.get(
            "https://api.upstox.com/v2/option/contract",
            params={"instrument_key": inst_key},
            headers=HEADERS, timeout=10,
        )
        d = r.json()
        exps = sorted({c.get("expiry") for c in (d.get("data") or []) if c.get("expiry")})
        upcoming = [e for e in exps if e >= today_key]
        if upcoming:
            return upcoming[0]
    except Exception:
        pass
    return None


def _candles_to_df(candles):
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles, columns=[
        "datetime", "open", "high", "low", "close", "volume", "oi",
    ])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


@st.cache_data(ttl=30, show_spinner=False)
def fetch_candles(timeframe: str, lookback_days: int = 15):
    unit, interval = TIMEFRAMES[timeframe]
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    from_date = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    hist = _fetch_historical_v3(NIFTY_KEY, unit, interval, today, from_date) or []
    intra = _fetch_intraday_v3(NIFTY_KEY, unit, interval) or []

    combined = hist + intra
    if not combined:
        return pd.DataFrame()

    df = _candles_to_df(combined)
    df = df.drop_duplicates(subset="datetime").reset_index(drop=True)
    return df


# ------------------------------------------------------------------ #
# SMC Engines
# ------------------------------------------------------------------ #
def find_swings(df, left=2, right=2):
    highs, lows = [], []
    if len(df) < left + right + 1:
        return highs, lows
    h = df["high"].values
    l = df["low"].values
    for i in range(left, len(df) - right):
        is_h = all(h[i] >= h[i - j] for j in range(1, left + 1)) and \
               all(h[i] >= h[i + j] for j in range(1, right + 1))
        is_l = all(l[i] <= l[i - j] for j in range(1, left + 1)) and \
               all(l[i] <= l[i + j] for j in range(1, right + 1))
        if is_h: highs.append(i)
        if is_l: lows.append(i)
    return highs, lows


def detect_bos_choch(df, swing_highs, swing_lows):
    events = []
    if not swing_highs and not swing_lows:
        return events

    swings = sorted(
        [("H", i, float(df["high"].iloc[i])) for i in swing_highs] +
        [("L", i, float(df["low"].iloc[i])) for i in swing_lows],
        key=lambda x: x[1],
    )

    trend = None
    last_h = None
    last_l = None
    si = 0

    for i in range(len(df)):
        close = float(df["close"].iloc[i])

        while si < len(swings) and swings[si][1] < i:
            kind, idx, price = swings[si]
            if kind == "H":
                last_h = (idx, price)
            else:
                last_l = (idx, price)
            si += 1

        if last_h is not None and close > last_h[1]:
            ev = "BOS" if trend == "up" else ("CHoCH" if trend == "down" else "BOS")
            events.append({"idx": i, "type": ev, "dir": "bullish",
                           "level": last_h[1], "ts": df["datetime"].iloc[i]})
            trend = "up"
            last_h = None
        elif last_l is not None and close < last_l[1]:
            ev = "BOS" if trend == "down" else ("CHoCH" if trend == "up" else "BOS")
            events.append({"idx": i, "type": ev, "dir": "bearish",
                           "level": last_l[1], "ts": df["datetime"].iloc[i]})
            trend = "down"
            last_l = None

    return events


def detect_fvg(df):
    fvgs = []
    if len(df) < 3:
        return fvgs
    highs = df["high"].values
    lows = df["low"].values

    for i in range(2, len(df)):
        if lows[i] > highs[i - 2]:
            fvgs.append({"idx": i, "type": "bullish",
                         "top": float(lows[i]), "bottom": float(highs[i - 2]),
                         "start_ts": df["datetime"].iloc[i - 2]})
        if highs[i] < lows[i - 2]:
            fvgs.append({"idx": i, "type": "bearish",
                         "top": float(lows[i - 2]), "bottom": float(highs[i]),
                         "start_ts": df["datetime"].iloc[i - 2]})

    # OPTIMIZED: Using Numpy arrays instead of Pandas slicing for 100x speed improvement
    for f in fvgs:
        if f["idx"] + 1 >= len(df):
            f["status"] = "fresh"
            continue

        if f["type"] == "bullish":
            if np.any(lows[f["idx"] + 1:] < f["bottom"]):
                f["status"] = "invalidated"
            elif np.any(lows[f["idx"] + 1:] <= f["top"]):
                f["status"] = "partially filled"
            else:
                f["status"] = "fresh"
        else:
            if np.any(highs[f["idx"] + 1:] > f["top"]):
                f["status"] = "invalidated"
            elif np.any(highs[f["idx"] + 1:] >= f["bottom"]):
                f["status"] = "partially filled"
            else:
                f["status"] = "fresh"

    return fvgs


def detect_order_blocks(df, bos_events, lookback=8):
    obs = []
    if not bos_events:
        return obs

    highs = df["high"].values
    lows = df["low"].values
    body = (df["close"] - df["open"]).abs()
    avg_body = body.rolling(20, min_periods=5).mean()

    for ev in bos_events:
        i = ev["idx"]
        if i < 2:
            continue

        displacement = body.iloc[i] > (avg_body.iloc[i] or 0) * 1.2
        if not displacement:
            continue

        if ev["dir"] == "bullish":
            for j in range(i - 1, max(0, i - lookback - 1), -1):
                if df["close"].iloc[j] < df["open"].iloc[j]:
                    obs.append({"idx": j, "type": "bullish",
                                "top": float(highs[j]),
                                "bottom": float(lows[j]),
                                "trigger_ts": df["datetime"].iloc[i],
                                "trigger_idx": i})
                    break
        else:
            for j in range(i - 1, max(0, i - lookback - 1), -1):
                if df["close"].iloc[j] > df["open"].iloc[j]:
                    obs.append({"idx": j, "type": "bearish",
                                "top": float(highs[j]),
                                "bottom": float(lows[j]),
                                "trigger_ts": df["datetime"].iloc[i],
                                "trigger_idx": i})
                    break

    # OPTIMIZED: Using Numpy arrays instead of Pandas slicing for 100x speed improvement
    for ob in obs:
        if ob["trigger_idx"] + 1 >= len(df):
            ob["status"] = "fresh"
            continue

        if ob["type"] == "bullish":
            if np.any(lows[ob["trigger_idx"] + 1:] < ob["bottom"]):
                ob["status"] = "invalidated"
            elif np.any(lows[ob["trigger_idx"] + 1:] <= ob["top"]):
                ob["status"] = "mitigated"
            else:
                ob["status"] = "fresh"
        else:
            if np.any(highs[ob["trigger_idx"] + 1:] > ob["top"]):
                ob["status"] = "invalidated"
            elif np.any(highs[ob["trigger_idx"] + 1:] >= ob["bottom"]):
                ob["status"] = "mitigated"
            else:
                ob["status"] = "fresh"

    return obs


def detect_liquidity(df, swing_highs, swing_lows):
    liq = []
    if df.empty:
        return liq

    tol = df["high"].mean() * 0.0003

    for i in swing_highs:
        liq.append({"idx": i, "type": "BSL",
                    "price": float(df["high"].iloc[i]), "kind": "swing high"})
    for i in swing_lows:
        liq.append({"idx": i, "type": "SSL",
                    "price": float(df["low"].iloc[i]), "kind": "swing low"})

    for a in range(len(swing_highs)):
        for b in range(a + 1, len(swing_highs)):
            ia, ib = swing_highs[a], swing_highs[b]
            pa, pb = float(df["high"].iloc[ia]), float(df["high"].iloc[ib])
            if abs(pa - pb) <= tol:
                liq.append({"idx": ib, "type": "BSL",
                            "price": max(pa, pb), "kind": "equal highs"})
    for a in range(len(swing_lows)):
        for b in range(a + 1, len(swing_lows)):
            ia, ib = swing_lows[a], swing_lows[b]
            pa, pb = float(df["low"].iloc[ia]), float(df["low"].iloc[ib])
            if abs(pa - pb) <= tol:
                liq.append({"idx": ib, "type": "SSL",
                            "price": min(pa, pb), "kind": "equal lows"})

    dts = df["datetime"].dt.date
    if len(df):
        today = dts.iloc[-1]
        prev_days = sorted(set(dts) - {today})
        if prev_days:
            pdf = df[dts == prev_days[-1]]
            liq.append({"idx": -1, "type": "PDH",
                        "price": float(pdf["high"].max()), "kind": "prev day high"})
            liq.append({"idx": -1, "type": "PDL",
                        "price": float(pdf["low"].min()), "kind": "prev day low"})

        df2 = df.copy()
        df2["week"] = df2["datetime"].dt.isocalendar().week
        cur_week = df2["week"].iloc[-1]
        prev_weeks = sorted(set(df2["week"]) - {cur_week})
        if prev_weeks:
            pwf = df2[df2["week"] == prev_weeks[-1]]
            liq.append({"idx": -1, "type": "PWH",
                        "price": float(pwf["high"].max()), "kind": "prev week high"})
            liq.append({"idx": -1, "type": "PWL",
                        "price": float(pwf["low"].min()), "kind": "prev week low"})

        sess = df[dts == today]
        if len(sess):
            liq.append({"idx": -1, "type": "SH",
                        "price": float(sess["high"].max()), "kind": "session high"})
            liq.append({"idx": -1, "type": "SL",
                        "price": float(sess["low"].min()), "kind": "session low"})

    return liq


def detect_sweeps(df, liq_levels):
    sweeps = []
    if df.empty:
        return sweeps
    for level in liq_levels:
        if level["idx"] < 0:
            continue
        price = level["price"]
        for i in range(level["idx"] + 1, len(df)):
            c = df.iloc[i]
            if level["type"] == "BSL":
                if c["high"] > price and c["close"] < price:
                    sweeps.append({"idx": i, "type": "bearish sweep",
                                   "level": price, "ts": df["datetime"].iloc[i],
                                   "kind": level["kind"]})
                    break
            else:
                if c["low"] < price and c["close"] > price:
                    sweeps.append({"idx": i, "type": "bullish sweep",
                                   "level": price, "ts": df["datetime"].iloc[i],
                                   "kind": level["kind"]})
                    break
    return sweeps


def classify_trend(df, swing_highs, swing_lows):
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "unclear"
    hh = swing_highs[-1] > swing_highs[-2]
    hl = swing_lows[-1] > swing_lows[-2]
    lh = swing_highs[-1] < swing_highs[-2]
    ll = swing_lows[-1] < swing_lows[-2]
    if hh and hl: return "trending bullish"
    if lh and ll: return "trending bearish"
    return "range / sideways"


def detect_sideways(df, swing_highs, swing_lows, lookback=20):
    if len(df) < lookback:
        return "unclear"
    recent = df.iloc[-lookback:]
    hi = float(recent["high"].max())
    lo = float(recent["low"].min())
    rng_pct = (hi - lo) / lo * 100 if lo > 0 else 0
    recent_sh = [i for i in swing_highs if i >= len(df) - lookback]
    recent_sl = [i for i in swing_lows if i >= len(df) - lookback]
    if rng_pct < 0.3 and recent_sh and recent_sl:
        return "sideways"
    if rng_pct < 0.5 and (len(recent_sh) + len(recent_sl)) >= 3:
        return "sideways"
    return "not sideways"


def premium_discount(df):
    if df.empty:
        return None
    hi = float(df["high"].max())
    lo = float(df["low"].min())
    cur = float(df["close"].iloc[-1])
    if hi <= lo:
        return None
    eq = (hi + lo) / 2
    return {"top": hi, "bottom": lo, "eq": eq, "current": cur,
            "zone": "premium" if cur > eq else "discount"}


# ------------------------------------------------------------------ #
# Pure Change-in-OI Flip Meter
# ------------------------------------------------------------------ #
def compute_pure_change_oi(change_oi_resp, spot_price, window=6):
    if not change_oi_resp or change_oi_resp.get("status") != "success" or spot_price <= 0:
        return None
    items = (change_oi_resp.get("data") or {}).get("call_put_oi_data_list") or []
    if not items:
        return None

    rows = sorted(items, key=lambda x: x.get("strike_price", 0))
    strikes = [r["strike_price"] for r in rows]
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot_price))
    lo = max(0, atm_idx - window)
    hi = min(len(rows), atm_idx + window + 1)
    sub = rows[lo:hi]

    total_pe = sum(float(r.get("put_change_oi", 0) or 0) for r in sub)
    total_ce = sum(float(r.get("call_change_oi", 0) or 0) for r in sub)
    denom = abs(total_pe) + abs(total_ce)
    score = (100.0 * (total_pe - total_ce) / denom) if denom > 0 else 0.0
    score = max(-100.0, min(100.0, score))

    if score >= 60:    status = "Strong bullish-side OI bias"
    elif score >= 20:  status = "Moderate bullish-side OI bias"
    elif score >= -19: status = "Neutral"
    elif score >= -59: status = "Moderate bearish-side OI bias"
    else:              status = "Strong bearish-side OI bias"

    return {"score": score, "status": status,
            "total_pe": total_pe, "total_ce": total_ce,
            "net": total_pe - total_ce,
            "atm": strikes[atm_idx],
            "range": (strikes[lo], strikes[hi - 1]),
            "n": len(sub)}


def _fmt_oi(v):
    a = abs(v)
    sign = "+" if v > 0 else ("-" if v < 0 else "")
    if a >= 1e7: return f"{sign}{a/1e7:.2f} Cr"
    if a >= 1e5: return f"{sign}{a/1e5:.2f} L"
    if a >= 1e3: return f"{sign}{a/1e3:.1f} K"
    return f"{sign}{a:.0f}"


# ------------------------------------------------------------------ #
# Chart renderer
# ------------------------------------------------------------------ #
def render_chart(df, swings, bos_choch, fvgs, obs, liq, sweeps,
                 pdz, timeframe, title="Nifty 50"):
    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=df["datetime"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name="Nifty",
        increasing_line_color="#26a69a", increasing_fillcolor="#26a69a",
        decreasing_line_color="#ef5350", decreasing_fillcolor="#ef5350",
    ))

    sh, sl = swings
    if sh:
        fig.add_trace(go.Scatter(
            x=[df["datetime"].iloc[i] for i in sh],
            y=[float(df["high"].iloc[i]) for i in sh],
            mode="markers", name="Swing High",
            marker=dict(symbol="triangle-down", size=9, color="#d32f2f"),
        ))
    if sl:
        fig.add_trace(go.Scatter(
            x=[df["datetime"].iloc[i] for i in sl],
            y=[float(df["low"].iloc[i]) for i in sl],
            mode="markers", name="Swing Low",
            marker=dict(symbol="triangle-up", size=9, color="#388e3c"),
        ))

    for f in fvgs[-15:]:
        color = "rgba(38,166,154,0.16)" if f["type"] == "bullish" else "rgba(239,83,80,0.16)"
        fig.add_shape(type="rect",
                      x0=f["start_ts"], x1=df["datetime"].iloc[-1],
                      y0=f["bottom"], y1=f["top"],
                      fillcolor=color, line=dict(width=0), layer="below")

    for ob in obs[-12:]:
        color = "rgba(56,142,60,0.14)" if ob["type"] == "bullish" else "rgba(211,47,47,0.14)"
        fig.add_shape(type="rect",
                      x0=df["datetime"].iloc[ob["idx"]], x1=df["datetime"].iloc[-1],
                      y0=ob["bottom"], y1=ob["top"],
                      fillcolor=color, line=dict(width=0), layer="below")

    for ev in bos_choch[-15:]:
        color = "#2e7d32" if ev["dir"] == "bullish" else "#c62828"
        fig.add_annotation(
            x=df["datetime"].iloc[ev["idx"]], y=ev["level"],
            text=f"{ev['type']}", showarrow=True, arrowhead=2, arrowcolor=color,
            ax=0, ay=-28 if ev["dir"] == "bullish" else 28,
            font=dict(color=color, size=10),
            bgcolor="rgba(255,255,255,0.85)", borderpad=2,
        )

    for level in liq:
        if level["idx"] < 0:
            is_high = level["type"] in ("PDH", "PWH", "SH")
            color = "#1565c0" if is_high else "#6a1b9a"
            fig.add_hline(y=level["price"], line_dash="dot",
                          line_color=color, line_width=1,
                          annotation_text=f"{level['type']} {level['price']:.0f}",
                          annotation_position="right",
                          annotation_font_size=9)

    for sw in sweeps[-12:]:
        color = "#2e7d32" if "bullish" in sw["type"] else "#c62828"
        fig.add_annotation(x=sw["ts"], y=sw["level"], text="⚡",
                           showarrow=False, font=dict(size=15, color=color))

    if pdz:
        fig.add_hline(y=pdz["eq"], line_dash="dash",
                      line_color="#607d8b", line_width=1,
                      annotation_text="EQ (50%)", annotation_position="left",
                      annotation_font_size=9)

    fig.update_layout(
        title=f"{title} · {timeframe}",
        xaxis_rangeslider_visible=False,
        height=720,
        template="plotly_white",
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h", y=1.02, x=0),
        hovermode="x",  # CHANGED FROM "x unified" TO "x" FOR EXTREME PERFORMANCE BOOST
    )

    if timeframe not in ("Daily",):
        fig.update_xaxes(rangebreaks=[
            dict(bounds=["sat", "mon"]),
            dict(bounds=[15.5, 9.25], pattern="hour"),
        ])

    return fig


# ------------------------------------------------------------------ #
# Price header
# ------------------------------------------------------------------ #
def render_nifty_price_bar():
    """Nifty spot price + change + change% banner. Called at top of page."""
    q = _fetch_nifty_quote()
    if q is None:
        st.markdown(
            '<div style="background:#fff3cd; padding:12px 18px; border-radius:10px; '
            'border-left:5px solid #ffc107; color:#856404; font-weight:600;">'
            '⚠️ Nifty live quote unavailable right now.</div>',
            unsafe_allow_html=True,
        )
        return None

    is_up = q["change"] >= 0
    color = "#00873c" if is_up else "#eb4444"
    bg = "#e8f5e9" if is_up else "#ffebee"
    arrow = "▲" if is_up else "▼"

    st.markdown(
        f'<div style="background:{bg}; padding:16px 22px; border-radius:12px; '
        f'border-left:5px solid {color}; margin-bottom:16px; color:#000; '
        f'box-shadow:0 2px 8px rgba(0,0,0,0.05);">'
        f'<div style="display:flex; justify-content:space-between; align-items:center; '
        f'flex-wrap:wrap; gap:12px;">'
        f'<div>'
        f'<div style="font-size:0.82rem; color:#555; font-weight:700; '
        f'text-transform:uppercase; letter-spacing:0.6px;">🇮🇳 Nifty 50 · Spot</div>'
        f'<div style="font-size:2.3rem; font-weight:800; margin-top:2px; '
        f'line-height:1.1;">{q["last"]:,.2f}</div>'
        f'<div style="font-size:0.75rem; color:#777; margin-top:2px;">'
        f'Prev close: {q["prev_close"]:,.2f}</div>'
        f'</div>'
        f'<div style="text-align:right;">'
        f'<div style="font-size:1.35rem; font-weight:800; color:{color};">'
        f'{arrow} {q["change"]:+,.2f}</div>'
        f'<div style="font-size:1.15rem; font-weight:700; color:{color}; '
        f'margin-top:2px;">({q["pct"]:+.2f}%)</div>'
        f'</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    return q


# ------------------------------------------------------------------ #
# Analysis summary
# ------------------------------------------------------------------ #
def _render_summary(df, swings, bos_choch, fvgs, obs, liq, sweeps, pdz, trend, sideways):
    last_close = float(df["close"].iloc[-1])
    last_ts = df["datetime"].iloc[-1]

    st.markdown(
        f"**Spot:** `{last_close:,.2f}` · "
        f"**Last candle:** `{last_ts.strftime('%Y-%m-%d %H:%M')}` · "
        f"**Trend:** `{trend}` · **Structure:** `{sideways}`"
    )

    c1, c2, c3, c4 = st.columns(4)
    fresh_fvgs = [f for f in fvgs if f["status"] == "fresh"]
    fresh_obs = [o for o in obs if o["status"] == "fresh"]
    c1.metric("Fresh FVGs", len(fresh_fvgs))
    c2.metric("Fresh Order Blocks", len(fresh_obs))
    c3.metric("Liquidity Levels", len(liq))
    c4.metric("Recent Sweeps", len(sweeps))

    if pdz:
        st.caption(
            f"Dealing range: {pdz['bottom']:,.0f} – {pdz['top']:,.0f} · "
            f"Equilibrium {pdz['eq']:,.0f} · Currently in **{pdz['zone'].upper()}** zone"
        )

    recent_bos = [e for e in bos_choch if e["idx"] >= len(df) - 15]
    if recent_bos:
        text = ", ".join(f"{e['type']} ({e['dir']}) @ {e['level']:,.0f}" for e in recent_bos[-4:])
        st.caption(f"Recent structure events: {text}")

    if sideways == "sideways":
        st.warning("⚠️ Sideways / consolidation structure — directional setups not recommended here.")
    elif trend == "trending bullish":
        st.success("Bullish structure bias")
    elif trend == "trending bearish":
        st.error("Bearish structure bias")


# ------------------------------------------------------------------ #
# Pure Change-in-OI panel
# ------------------------------------------------------------------ #
def _render_pure_oi_panel(spot_price, expiry_str):
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    resp = _fetch_change_oi(NIFTY_KEY, expiry_str, today_str)
    result = compute_pure_change_oi(resp, spot_price)

    st.markdown("#### 🧪 Pure Change-in-OI Flip Meter")
    st.caption(
        "13-strike window (ATM ±6). Score = 100 × (Σ Put ΔOI − Σ Call ΔOI) "
        "/ (|Σ Put ΔOI| + |Σ Call ΔOI|). No greeks, no weights, no premiums."
    )

    if result is None:
        st.info("Change-in-OI data unavailable right now.")
        return None

    score = result["score"]
    color = "#2e7d32" if score >= 20 else "#c62828" if score <= -20 else "#6e7781"

    cA, cB, cC = st.columns(3)
    cA.metric("Pure Score", f"{score:+.1f}", help=result["status"])
    cB.metric("Σ Put ΔOI", _fmt_oi(result["total_pe"]))
    cC.metric("Σ Call ΔOI", _fmt_oi(result["total_ce"]))

    st.markdown(
        f'<div style="background:#f4f7f9; padding:10px 14px; border-radius:8px; '
        f'border-left:4px solid {color}; color:#000; font-size:0.92rem;">'
        f'<b>Status:</b> {result["status"]} · '
        f'<b>Net ΔOI (PE−CE):</b> {_fmt_oi(result["net"])} · '
        f'<b>ATM:</b> {result["atm"]:,.0f} · '
        f'<b>Range:</b> {result["range"][0]:,.0f} – {result["range"][1]:,.0f} · '
        f'<b>Strikes:</b> {result["n"]}'
        f'</div>',
        unsafe_allow_html=True,
    )
    return result


# ------------------------------------------------------------------ #
# Main section renderer (importable)
# ------------------------------------------------------------------ #
def render_smc_section(expiry_str=None):
    st.markdown("## 📈 Nifty Chart + Smart Money Concepts")

    if not PLOTLY_AVAILABLE:
        st.error("Plotly is required. Install with `pip install plotly`.")
        return

    col_tf, col_lookback = st.columns([2, 3])
    with col_tf:
        tf = st.selectbox("Timeframe", list(TIMEFRAMES.keys()), index=2, key="smc_tf")
    with col_lookback:
        lookback = st.slider("Lookback (days)", 3, 30, 15, 1, key="smc_lookback")

    df = fetch_candles(tf, lookback)
    if df.empty:
        st.warning("No candle data available (market closed or API issue).")
        return

    # --- PERFORMANCE OPTIMIZATION: Cap candles to prevent browser freeze ---
    # 1-minute charts over 15 days generate >5000 candles.
    # Plotly becomes extremely laggy with >1000 points. We cap it to the most recent 1000.
    max_candles = 1000
    if len(df) > max_candles:
        df = df.tail(max_candles).reset_index(drop=True)

    swing_highs, swing_lows = find_swings(df)
    bos_choch = detect_bos_choch(df, swing_highs, swing_lows)
    fvgs = detect_fvg(df)
    obs = detect_order_blocks(df, bos_choch)
    liq = detect_liquidity(df, swing_highs, swing_lows)
    sweeps = detect_sweeps(df, liq)
    pdz = premium_discount(df)
    trend = classify_trend(df, swing_highs, swing_lows)
    sideways = detect_sideways(df, swing_highs, swing_lows)

    fig = render_chart(df, (swing_highs, swing_lows), bos_choch, fvgs, obs, liq, sweeps, pdz, tf)
    st.plotly_chart(fig, use_container_width=True, key=f"smc_chart_{tf}")

    st.markdown("### 🔍 Structure Summary")
    _render_summary(df, (swing_highs, swing_lows), bos_choch, fvgs, obs, liq, sweeps, pdz, trend, sideways)

    with st.expander("🧾 Recent Zones (raw)", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Fresh FVGs**")
            fresh = [f for f in fvgs if f["status"] == "fresh"][-6:]
            if fresh:
                for f in fresh:
                    st.caption(
                        f"{f['type'].title()} FVG · {f['bottom']:,.1f} – {f['top']:,.1f} "
                        f"(since {f['start_ts'].strftime('%H:%M')})"
                    )
            else:
                st.caption("None")
        with col2:
            st.markdown("**Fresh Order Blocks**")
            fresh_ob = [o for o in obs if o["status"] == "fresh"][-6:]
            if fresh_ob:
                for o in fresh_ob:
                    st.caption(
                        f"{o['type'].title()} OB · {o['bottom']:,.1f} – {o['top']:,.1f} "
                        f"(triggered {o['trigger_ts'].strftime('%H:%M')})"
                    )
            else:
                st.caption("None")

    with st.expander("⚡ Liquidity & Sweeps (raw)", expanded=False):
        if sweeps:
            for sw in sweeps[-8:]:
                st.caption(
                    f"{sw['type'].title()} @ {sw['level']:,.1f} "
                    f"({sw['kind']}, {sw['ts'].strftime('%H:%M')})"
                )
        else:
            st.caption("No sweeps detected yet.")

    st.markdown("---")

    q = _fetch_nifty_quote()
    spot = q["last"] if q else float(df["close"].iloc[-1])

    if expiry_str is None:
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        expiry_str = _fetch_nearest_expiry(NIFTY_KEY, today_str) or today_str

    _render_pure_oi_panel(spot, expiry_str)

    st.caption(
        f"🛰️ Shadow-mode observation only — nothing here touches the existing signals, "
        f"gates, or alerts. Data: Upstox V3 candles · last refresh "
        f"{datetime.now(IST).strftime('%H:%M:%S')} IST"
    )


# ------------------------------------------------------------------ #
# Standalone runner
# ------------------------------------------------------------------ #
def _standalone_main():
    if "smc_page_cfg" not in st.session_state:
        st.set_page_config(
            page_title="Nifty SMC Chart",
            page_icon="📈",
            layout="wide",
        )
        st.session_state.smc_page_cfg = True

    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=15000, key="smc_standalone_refresh")
    except Exception:
        pass

    st.title("📈 Nifty 50 — Chart + Smart Money Concepts (Standalone)")
    render_nifty_price_bar()
    render_smc_section()


if __name__ == "__main__":
    _standalone_main()
