"""
smart_oi_snapshots.py — 5-MINUTE MARKET RECORDER (shadow / read-only)

Every 5 minutes during market hours it writes ONE row with everything your app has
already fetched: Nifty price/change/5-min bar, OI, change in OI, option-chain
premiums/volume/IV, futures list, VIX and global cues, plus the state of your existing
meters. It makes NO API calls of its own and never changes any signal.

* One row per 5-minute bucket (id = "YYYY-MM-DD HH:MM"), so even if two browser tabs are
  open they write the SAME row instead of duplicates.
* Missing data stays blank. It is never turned into zero.
* Saved to alerts repo folder  snapshots/YYYY-MM-DD_snapshots.csv  (same private repo).
"""
import json
import math
from datetime import datetime, time, timedelta

import smart_oi_store as _store

SNAP_PATH_DEFAULT = "smart_oi_snapshots.jsonl"
SNAP_FOLDER, SNAP_SUFFIX = "snapshots", "snapshots"
BUCKET_MIN = 5
OI_WINDOW = 6            # strikes each side of ATM for the OI window (like your Flip Meter)
COI_WINDOW = 10          # strikes each side of ATM for change-in-OI (like your Reversal Meter)
BAND_STRIKES = 8         # option-chain band stored in full (ATM +/- 8 strikes)
BAR_MIN_SAMPLES = 6      # a 5-minute bar needs at least 6 of its ~60 five-second samples
MARKET_OPEN, MARKET_CLOSE = time(9, 15), time(15, 30)
RELIABLE_PAGE_AGE_SEC = 60

SNAP_COLUMNS = [
    "id", "ts", "bucket", "late_sec", "page_age_sec", "data_reliable", "missing_fields",
    "spot", "prev_close", "change", "change_pct",
    "bar_open", "bar_high", "bar_low", "bar_close", "bar_samples",
    "oi_total_call", "oi_total_put", "oi_pcr", "oi_atm_strike", "oi_win_call", "oi_win_put",
    "oi_max_call_strike", "oi_max_call", "oi_max_put_strike", "oi_max_put",
    "coi_total_call", "coi_total_put", "coi_win_call", "coi_win_put",
    "coi_max_call_strike", "coi_max_call", "coi_max_put_strike", "coi_max_put",
    "ch_atm_strike", "ch_atm_call_ltp", "ch_atm_put_ltp", "ch_straddle",
    "ch_atm_call_iv", "ch_atm_put_iv", "ch_atm_call_oi", "ch_atm_put_oi",
    "ch_atm_call_vol", "ch_atm_put_vol",
    "ch_call_vol_total", "ch_put_vol_total", "ch_vol_pcr", "ch_call_oi_total", "ch_put_oi_total",
    "ch_oi_pcr", "ch_call_oi_chg", "ch_put_oi_chg", "ch_max_vol_call_strike", "ch_max_vol_put_strike",
    "ch_band_json",
    "fut_macro_score", "fut_count", "fut_json",
    "india_vix", "india_vix_pct", "us_vix", "gift_pct", "banknifty_fut_pct", "assets_json",
    "flip_score", "flip_state", "rev_bear_score", "rev_bull_score",
    "entry_signal", "entry_strike", "entry_trigger", "entry_status", "gate_verdict", "exit_signal",
    "p2_color", "p2_price_dir", "p2_sideways", "p2_oi_bias", "p3_active", "spot_age_sec", "oi_age_sec",
]


# ------------------------------------------------------------------ helpers
def _f(x):
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _r(x, nd=4):
    v = _f(x)
    return None if v is None else round(v, nd)


def _ssum(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def _ratio(a, b):
    return (a / b) if (a is not None and b not in (None, 0)) else None


def in_session(now):
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def bucket_of(now, minutes=BUCKET_MIN):
    return now.replace(minute=(now.minute // minutes) * minutes, second=0, microsecond=0)


def _argmax(pairs):
    """pairs = [(strike, value)] with None values ignored. Returns (strike, value) or (None, None)."""
    pairs = [(k, v) for k, v in pairs if v is not None]
    if not pairs:
        return None, None
    return max(pairs, key=lambda kv: kv[1])


# ------------------------------------------------------------- summarisers
def _strike_rows(items):
    rows = [it for it in items if _f(it.get("strike_price")) is not None]
    return sorted(rows, key=lambda it: _f(it["strike_price"]))


def _window(rows, spot, n):
    if not rows or _f(spot) is None:
        return None, []
    strikes = [_f(r["strike_price"]) for r in rows]
    idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    return strikes[idx], rows[max(0, idx - n): idx + n + 1]


def _oi_items(resp):
    if not isinstance(resp, dict) or resp.get("status") != "success":
        return []
    return (resp.get("data") or {}).get("call_put_oi_data_list") or []


def summarize_oi(resp, spot):
    rows = _strike_rows(_oi_items(resp))
    if not rows:
        return {}
    calls = [_f(r.get("call_oi")) for r in rows]
    puts = [_f(r.get("put_oi")) for r in rows]
    tc, tp = _ssum(calls), _ssum(puts)
    atm, win = _window(rows, spot, OI_WINDOW)
    ks = [_f(r["strike_price"]) for r in rows]
    mc, mcv = _argmax(list(zip(ks, calls)))
    mp, mpv = _argmax(list(zip(ks, puts)))
    return {"oi_total_call": tc, "oi_total_put": tp, "oi_pcr": _r(_ratio(tp, tc)),
            "oi_atm_strike": atm,
            "oi_win_call": _ssum([_f(r.get("call_oi")) for r in win]) if win else None,
            "oi_win_put": _ssum([_f(r.get("put_oi")) for r in win]) if win else None,
            "oi_max_call_strike": mc, "oi_max_call": mcv, "oi_max_put_strike": mp, "oi_max_put": mpv}


def summarize_change_oi(resp, spot):
    rows = _strike_rows(_oi_items(resp))
    if not rows:
        return {}
    calls = [_f(r.get("call_change_oi")) for r in rows]
    puts = [_f(r.get("put_change_oi")) for r in rows]
    _, win = _window(rows, spot, COI_WINDOW)
    ks = [_f(r["strike_price"]) for r in rows]
    mc, mcv = _argmax(list(zip(ks, calls)))
    mp, mpv = _argmax(list(zip(ks, puts)))
    return {"coi_total_call": _ssum(calls), "coi_total_put": _ssum(puts),
            "coi_win_call": _ssum([_f(r.get("call_change_oi")) for r in win]) if win else None,
            "coi_win_put": _ssum([_f(r.get("put_change_oi")) for r in win]) if win else None,
            "coi_max_call_strike": mc, "coi_max_call": mcv, "coi_max_put_strike": mp, "coi_max_put": mpv}


def _leg(it, side):
    o = it.get(f"{side}_options") or {}
    md, gk = o.get("market_data") or {}, o.get("option_greeks") or {}
    return {"ltp": _f(md.get("ltp")), "oi": _f(md.get("oi")), "prev_oi": _f(md.get("prev_oi")),
            "vol": _f(md.get("volume")), "iv": _f(gk.get("iv"))}


_LEG_KEYS = ("ltp", "oi", "prev_oi", "vol", "iv")


def summarize_chain(resp, spot):
    """Returns (summary dict, list of missing-field names)."""
    if not isinstance(resp, dict) or resp.get("status") != "success" or not isinstance(resp.get("data"), list):
        return {}, ["chain"]
    rows = _strike_rows(resp["data"])
    if not rows:
        return {}, ["chain"]
    legs = [(_f(r["strike_price"]), _leg(r, "call"), _leg(r, "put")) for r in rows]
    tot = lambda side, key: _ssum([(c if side == "c" else p)[key] for _, c, p in legs])
    chg = lambda i: _ssum([(x["oi"] - x["prev_oi"]) for _, c, p in legs for x in [(c, p)[i]]
                           if x["oi"] is not None and x["prev_oi"] is not None])
    cv, pv, co, po = tot("c", "vol"), tot("p", "vol"), tot("c", "oi"), tot("p", "oi")
    atm, _ = _window(rows, spot, 0)
    out = {"ch_atm_strike": atm, "ch_call_vol_total": cv, "ch_put_vol_total": pv,
           "ch_vol_pcr": _r(_ratio(pv, cv)), "ch_call_oi_total": co, "ch_put_oi_total": po,
           "ch_oi_pcr": _r(_ratio(po, co)), "ch_call_oi_chg": chg(0), "ch_put_oi_chg": chg(1)}
    missing = []
    if atm is not None:
        _, c, p = next(x for x in legs if x[0] == atm)
        out.update({"ch_atm_call_ltp": c["ltp"], "ch_atm_put_ltp": p["ltp"],
                    "ch_straddle": (c["ltp"] + p["ltp"]) if (c["ltp"] is not None and p["ltp"] is not None) else None,
                    "ch_atm_call_iv": c["iv"], "ch_atm_put_iv": p["iv"], "ch_atm_call_oi": c["oi"],
                    "ch_atm_put_oi": p["oi"], "ch_atm_call_vol": c["vol"], "ch_atm_put_vol": p["vol"]})
        missing = [f"atm_{s}_{k}" for s, leg in (("call", c), ("put", p)) for k in _LEG_KEYS if leg[k] is None]
    ks = [k for k, _, _ in legs]
    out["ch_max_vol_call_strike"], _ = _argmax([(k, c["vol"]) for k, c, _ in legs])
    out["ch_max_vol_put_strike"], _ = _argmax([(k, p["vol"]) for k, _, p in legs])
    if atm is not None:
        i = ks.index(atm)
        band = [[k] + [c[x] for x in _LEG_KEYS] + [p[x] for x in _LEG_KEYS]
                for k, c, p in legs[max(0, i - BAND_STRIKES): i + BAND_STRIKES + 1]]
        out["ch_band_json"] = json.dumps(band, separators=(",", ":"))   # [strike, call ltp,oi,prev_oi,vol,iv, put ...]
    return out, missing


def summarize_futures(resp, score=None):
    out = {"fut_macro_score": _r(score)}
    smart = ((resp or {}).get("data") or {}).get("smartlist") if isinstance(resp, dict) else None
    if not isinstance(smart, list):
        return out, ["futures"]
    rows = []
    for it in smart[:20]:
        m, pr = it.get("metric") or {}, it.get("price") or {}
        rows.append([it.get("instrument_key"), _f(m.get("current")), _f(m.get("change_abs")),
                     _f(m.get("change_pct")), _f(pr.get("change_pct")),
                     _f(pr.get("current", pr.get("last_price")))])
    out["fut_count"] = len(rows)
    out["fut_json"] = json.dumps(rows, separators=(",", ":"))     # [key, metric, metric chg, metric chg %, price chg %, price]
    return out, []


def summarize_assets(assets):
    d = {}
    for name, close, pct in (assets or []):
        if _f(close):                                              # 0 / None = instrument not fetched
            d[name] = [_r(close, 2), _r(pct, 2)]
    return ({"assets_json": json.dumps(d, separators=(",", ":"))} if d else {})


def bar_ohlc(spot_buf, start, end):
    """The 5-minute bar [start, end) built from the 5-second spot samples. None if too few samples."""
    vals = [s["spot"] for s in spot_buf if start <= s["ts"] < end]
    if len(vals) < BAR_MIN_SAMPLES:
        return {"bar_samples": len(vals)}
    return {"bar_open": vals[0], "bar_high": max(vals), "bar_low": min(vals), "bar_close": vals[-1],
            "bar_samples": len(vals)}


# ---------------------------------------------------------------- the row
def build_row(now, bucket, inp, p1):
    spot = _f(inp.get("spot"))
    prev = _f(inp.get("prev_close"))
    rep = p1.get("last_report") or {}
    feeds = rep.get("feeds") or {}
    row = {"id": bucket.strftime("%Y-%m-%d %H:%M"), "ts": now.isoformat(), "bucket": bucket.strftime("%H:%M"),
           "late_sec": int((now - bucket).total_seconds()), "page_age_sec": _r(inp.get("page_age_sec"), 1),
           "spot": spot, "prev_close": prev}
    if spot is not None and prev:
        row["change"] = round(spot - prev, 2)
        row["change_pct"] = round((spot - prev) / prev * 100, 3)
    row.update(bar_ohlc(p1.get("spot_buf") or [], bucket - timedelta(minutes=BUCKET_MIN), bucket))
    missing = []
    for name, part in (("oi", summarize_oi(inp.get("oi_resp"), spot)),
                       ("coi", summarize_change_oi(inp.get("coi_resp"), spot))):
        row.update(part)
        if not part:
            missing.append(name)
    chain, chain_missing = summarize_chain(inp.get("chain_resp"), spot)
    row.update(chain)
    missing += chain_missing
    fut, fut_missing = summarize_futures(inp.get("fut_resp"), inp.get("fut_score"))
    row.update(fut)
    missing += fut_missing
    row.update(summarize_assets(inp.get("assets")))
    row.update({"india_vix": _r(inp.get("india_vix"), 2), "india_vix_pct": _r(inp.get("india_vix_pct"), 2),
                "us_vix": _r(inp.get("us_vix"), 2), "gift_pct": _r(inp.get("gift_pct"), 3),
                "banknifty_fut_pct": _r(inp.get("bnf_pct"), 3)})
    entry, ext = inp.get("entry") or {}, inp.get("exit") or {}
    row.update({"flip_score": _r(inp.get("flip_score"), 2), "flip_state": inp.get("flip_state"),
                "rev_bear_score": _r(inp.get("rev_bear"), 1), "rev_bull_score": _r(inp.get("rev_bull"), 1),
                "entry_signal": entry.get("signal"), "entry_strike": entry.get("strike"),
                "entry_trigger": entry.get("trigger_price"), "entry_status": entry.get("status_label"),
                "gate_verdict": inp.get("gate"), "exit_signal": ext.get("signal")})
    p2 = p1.get("p2") or {}
    p3 = p1.get("p3") or {}
    row.update({"p2_color": p2.get("color"), "p2_price_dir": p2.get("price_dir"),
                "p2_sideways": p2.get("sideways_status"), "p2_oi_bias": p2.get("bias"),
                "p3_active": sum(1 for v in (p3.get("active") or {}).values() if v)})
    sp_age = (feeds.get("spot") or {}).get("age")
    oi_age = (feeds.get("oi") or {}).get("age")
    row["spot_age_sec"], row["oi_age_sec"] = _r(sp_age, 1), _r(oi_age, 1)
    if spot is None:
        missing.append("spot")
    page_ok = _f(inp.get("page_age_sec")) is not None and inp["page_age_sec"] <= RELIABLE_PAGE_AGE_SEC
    if not page_ok:
        missing.append("page_stale")
    row["data_reliable"] = bool(rep.get("reliable")) and spot is not None and page_ok
    row["missing_fields"] = ",".join(missing)
    return {k: row.get(k) for k in SNAP_COLUMNS}


# ------------------------------------------------------------- persistence
def new_snap_state():
    return {"done": set(), "count": 0, "last": None, "missing": {}, "errors": 0, "last_error": None,
            "gh": _store.new_gh_state(), "log_errors": 0}


def _append(path, rec):
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


def load_snaps(path):
    rows = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("type") == "snap" and r.get("id"):
                    rows[r["id"]] = {c: ("" if r.get(c) is None else str(r.get(c))) for c in SNAP_COLUMNS}
    except OSError:
        return []
    return list(rows.values())


def maybe_snapshot(p1, now, inputs_fn, cfg=None, path=SNAP_PATH_DEFAULT, background=True):
    """Call every tick. Writes at most one row per 5-minute bucket, only while the market is open.
    Never raises; problems are shown on the Phase 1 panel."""
    sn = p1.setdefault("snap", new_snap_state())
    bid = None
    try:
        if in_session(now):
            bucket = bucket_of(now)
            bid = bucket.strftime("%Y-%m-%d %H:%M")
            if bid not in sn["done"]:
                sn["done"].add(bid)
                row = build_row(now, bucket, inputs_fn(), p1)
                _append(path, dict(row, type="snap"))
                sn["count"] += 1
                sn["last"] = row["bucket"]
                for name in [m for m in row["missing_fields"].split(",") if m]:
                    sn["missing"][name] = sn["missing"].get(name, 0) + 1
        _store.sync_table(sn["gh"], now, cfg, lambda: load_snaps(path), sn["count"],
                          SNAP_FOLDER, SNAP_SUFFIX, SNAP_COLUMNS, background=background)
    except Exception as e:
        if bid is not None:
            sn["done"].discard(bid)            # try again on the next tick
        sn["errors"] += 1
        sn["last_error"] = f"{type(e).__name__}: {str(e)[:80]}"
    return sn
