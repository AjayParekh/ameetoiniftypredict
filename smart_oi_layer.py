"""
smart_oi_layer.py — PHASE 1 (SHADOW MODE)

Data freshness, 5-second spot buffer, and an append-only alert log with
no-look-ahead 5/10/15-minute outcomes.

* No Streamlit import. Pure functions + one plain dict of state, so it can be
  unit-tested and can never change your existing meters.
* Reads your existing data only. Makes NO API calls of its own.
* Never treats a failed/empty response as zero. Never counts an unchanged
  (duplicate) response as a new observation.
"""
import json
import math
from datetime import datetime, time, timedelta

LOG_PATH_DEFAULT = "smart_oi_log.jsonl"
SPOT_KEEP_SEC = 5400                      # keep 90 min of spot samples
STALE_AFTER = {"spot": 20, "oi": 30, "premium": 30}   # seconds since last SUCCESS
HORIZONS = (5, 10, 15)                    # minutes
OUTCOME_TOLERANCE_SEC = 90                # outcome sample must be within 90 s AFTER target
ALERT_SPOT_MAX_BACK_SEC = 15              # spot-at-alert must be <=15 s before alert
PENDING_MAX_AGE_MIN = 20


# ------------------------------------------------------------------ helpers
def is_market_open(now):
    if now.weekday() >= 5:
        return False
    return time(9, 15) <= now.time() <= time(15, 30)


def _valid_price(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if (math.isfinite(x) and x > 0) else None


def _localize(naive, ref_dt):
    tz = ref_dt.tzinfo
    if tz is None:
        return naive
    return tz.localize(naive) if hasattr(tz, "localize") else naive.replace(tzinfo=tz)


def _direction_from_type(kind):
    k = str(kind).lower()
    if "bull" in k:
        return "BULLISH"
    if "bear" in k:
        return "BEARISH"
    return "UNKNOWN"


# -------------------------------------------------------------------- state
def _new_feed(enabled=True):
    return {"enabled": enabled, "last_success": None, "last_change": None,
            "last_hash": None, "ok": 0, "unchanged": 0, "errors": 0,
            "missing": 0, "last_error": None, "last_error_ts": None}


def new_state():
    return {"initialized": False,
            "spot_buf": [],
            "feeds": {"spot": _new_feed(), "oi": _new_feed(),
                      "premium": _new_feed(enabled=False)},   # premium arrives in Phase 4
            "seen_ids": set(),
            "pending": {},
            "logged": 0, "log_errors": 0, "last_log_error": None}


def record_feed(state, kind, now, ok, payload_hash=None, error=None, missing=False):
    """Returns True only if this is a NEW independent observation."""
    f = state["feeds"][kind]
    if not ok:
        f["missing" if missing else "errors"] += 1
        f["last_error"] = (str(error)[:200] if error
                           else ("missing data" if missing else "error"))
        f["last_error_ts"] = now
        return False
    f["last_success"] = now
    f["ok"] += 1
    if payload_hash is None or payload_hash != f["last_hash"]:
        f["last_hash"] = payload_hash
        f["last_change"] = now
        return True
    f["unchanged"] += 1
    return False


def record_spot(state, now, price):
    p = _valid_price(price)
    if p is None:
        record_feed(state, "spot", now, False, error="spot unavailable", missing=True)
        return False
    buf = state["spot_buf"]
    buf.append({"ts": now, "spot": p})
    cutoff = now - timedelta(seconds=SPOT_KEEP_SEC)
    state["spot_buf"] = [s for s in buf if s["ts"] >= cutoff]
    record_feed(state, "spot", now, True, payload_hash=p)
    return True


def _oi_hash(items):
    # None stays None (never coerced to 0), so a missing field is visible in the hash.
    return hash(tuple(sorted(
        (it.get("strike_price"), it.get("call_change_oi"), it.get("put_change_oi"))
        for it in items)))


def record_change_oi(state, now, resp, fetch_error=None):
    """Validate an already-fetched change-OI response. Returns True if NEW data."""
    if fetch_error is not None:
        return record_feed(state, "oi", now, False, error=f"fetch failed: {fetch_error}")
    if not isinstance(resp, dict):
        return record_feed(state, "oi", now, False, error="no response", missing=True)
    if resp.get("status") != "success":
        msg = resp.get("errors") or resp.get("message") or resp.get("status") or "unknown"
        return record_feed(state, "oi", now, False, error=f"API status: {msg}")
    items = (resp.get("data") or {}).get("call_put_oi_data_list") or []
    if not items:
        return record_feed(state, "oi", now, False, error="empty strike list", missing=True)
    return record_feed(state, "oi", now, True, payload_hash=_oi_hash(items))


# ----------------------------------------------------------------- freshness
def freshness_report(state, now):
    market_open = is_market_open(now)
    feeds = {}
    for kind, f in state["feeds"].items():
        age = (now - f["last_success"]).total_seconds() if f["last_success"] else None
        if not f["enabled"]:
            status = "NOT ENABLED"
        elif f["last_success"] is None:
            status = "NEVER"
        elif age > STALE_AFTER[kind]:
            status = "STALE"
        else:
            status = "FRESH"
        feeds[kind] = {"status": status, "age": age, "errors": f["errors"],
                       "missing": f["missing"], "unchanged": f["unchanged"],
                       "last_success": f["last_success"], "last_change": f["last_change"],
                       "last_error": f["last_error"]}
    if not market_open:
        reliable, reason = False, "Market closed"
    elif feeds["spot"]["status"] != "FRESH":
        reliable, reason = False, f"Spot {feeds['spot']['status']}"
    elif feeds["oi"]["status"] != "FRESH":
        reliable, reason = False, f"OI {feeds['oi']['status']}"
    else:
        reliable, reason = True, "OK"
    return {"feeds": feeds, "reliable": reliable, "reason": reason, "market_open": market_open}


# -------------------------------------------------------------- spot lookups
def spot_at_or_before(buf, ts, max_back_sec=ALERT_SPOT_MAX_BACK_SEC):
    best = None
    for s in buf:
        if s["ts"] <= ts and (ts - s["ts"]).total_seconds() <= max_back_sec:
            best = s
    return best


def spot_first_at_or_after(buf, ts):
    for s in buf:
        if s["ts"] >= ts:
            return s
    return None


# ------------------------------------------------------------------ log I/O
def _append(state, path, rec):
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
        state["logged"] += 1
        return True
    except OSError as e:
        state["log_errors"] += 1
        state["last_log_error"] = str(e)[:150]
        return False


def load_log(path):
    """Merge append-only events into one record per alert. Bad lines are skipped."""
    alerts, outcomes, bad = {}, {}, 0
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if r.get("type") == "alert":
                    alerts[r["id"]] = r
                elif r.get("type") == "outcome":
                    outcomes.setdefault(r["id"], {})[r["h"]] = r
    except OSError:
        return [], 0
    merged = []
    for aid, a in alerts.items():
        rec = dict(a)
        sgn = {"BULLISH": 1, "BEARISH": -1}.get(a.get("direction"))
        for h in HORIZONS:
            o = outcomes.get(aid, {}).get(h)
            price = o.get("price") if o else None
            rec[f"price_{h}m"] = price
            spot0 = a.get("spot_at_alert")
            rec[f"hit_{h}m"] = (None if (price is None or spot0 is None or sgn is None)
                                else (price - spot0) * sgn > 0)
        merged.append(rec)
    return merged, bad


# --------------------------------------------------------- alert synchronising
def _log_alert(state, path, now, rec):
    if _append(state, path, rec):
        state["pending"][rec["id"]] = {"ts": datetime.fromisoformat(rec["ts"]), "done": set()}


def _init_once(state, now, rev_alerts, flip_dir, flip_since, path):
    """Alerts that already exist when the layer starts are NOT logged (no spot/OI
    context for them) — they are only marked as seen."""
    for a in (rev_alerts or []):
        state["seen_ids"].add(f"{a.get('ts')}|{a.get('type')}")
    if flip_dir and flip_since:
        state["seen_ids"].add(f"{flip_since.strftime('%Y-%m-%d %H:%M:%S')}|flip_{flip_dir}")
    merged, _ = load_log(path)
    for r in merged:
        state["seen_ids"].add(r["id"])
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (KeyError, ValueError):
            continue
        age_min = (now - ts).total_seconds() / 60
        missing = [h for h in HORIZONS if r.get(f"price_{h}m") is None]
        if 0 <= age_min <= PENDING_MAX_AGE_MIN and missing:
            state["pending"][r["id"]] = {"ts": ts, "done": set(HORIZONS) - set(missing)}
    state["initialized"] = True


def _latest_snapshot_before(snapshots, ts):
    best = None
    for s in (snapshots or []):
        if s.get("ts") is not None and s["ts"] <= ts:
            best = s
    return best


def sync_alerts(state, now, rev_alerts, snapshots, flip_dir, flip_since, flip_score,
                report, path, p2=None):
    """Log NEW alerts from your original meters (source tagged so the original and
    the future confirmation layer can be compared separately)."""
    for a in (rev_alerts or []):
        aid = f"{a.get('ts')}|{a.get('type')}"
        if aid in state["seen_ids"]:
            continue
        state["seen_ids"].add(aid)
        try:
            ts = _localize(datetime.strptime(a["ts"], "%Y-%m-%d %H:%M:%S"), now)
        except (KeyError, ValueError):
            continue
        sp = spot_at_or_before(state["spot_buf"], ts)
        snap = _latest_snapshot_before(snapshots, ts)
        _log_alert(state, path, now, {
            "type": "alert", "id": aid, "ts": ts.isoformat(),
            "source": "original_reversal", "direction": _direction_from_type(a.get("type")),
            "spot_at_alert": sp["spot"] if sp else None,
            "oi_flip_score": flip_score,
            "call_oi_change": snap.get("ce") if snap else None,
            "put_oi_change": snap.get("pe") if snap else None,
            **_p2_fields(p2),
            "data_reliable": report["reliable"], "msg": a.get("msg")})
    if flip_dir and flip_since:
        fid = f"{flip_since.strftime('%Y-%m-%d %H:%M:%S')}|flip_{flip_dir}"
        if fid not in state["seen_ids"]:
            state["seen_ids"].add(fid)
            sp = spot_at_or_before(state["spot_buf"], flip_since)
            _log_alert(state, path, now, {
                "type": "alert", "id": fid, "ts": flip_since.isoformat(),
                "source": "original_flip", "direction": flip_dir,
                "spot_at_alert": sp["spot"] if sp else None,
                "oi_flip_score": flip_score, "call_oi_change": None, "put_oi_change": None,
                **_p2_fields(p2),
                "data_reliable": report["reliable"], "msg": f"OI Flip {flip_dir}"})


# ------------------------------------------------------------------ outcomes
def process_outcomes(state, now, path):
    """Price after 5/10/15 min = first recorded sample AT OR AFTER alert_ts + h.
    Never uses any sample earlier than the target (no look-ahead) and never
    back-fills a late sample: if none arrived within tolerance it is logged MISSING."""
    for aid in list(state["pending"].keys()):
        p = state["pending"][aid]
        for h in HORIZONS:
            if h in p["done"]:
                continue
            target = p["ts"] + timedelta(minutes=h)
            if now < target:
                continue
            s = spot_first_at_or_after(state["spot_buf"], target)
            if s and (s["ts"] - target).total_seconds() <= OUTCOME_TOLERANCE_SEC:
                _append(state, path, {"type": "outcome", "id": aid, "h": h,
                                      "price": s["spot"], "price_ts": s["ts"].isoformat(),
                                      "status": "OK"})
                p["done"].add(h)
            elif (now - target).total_seconds() > OUTCOME_TOLERANCE_SEC:
                _append(state, path, {"type": "outcome", "id": aid, "h": h,
                                      "price": None, "price_ts": None, "status": "MISSING"})
                p["done"].add(h)
        if len(p["done"]) == len(HORIZONS):
            del state["pending"][aid]


# ---------------------------------------------------------------------- tick
def tick(state, now, *, spot_raw, change_oi_resp, change_oi_error=None,
         rev_alerts=None, snapshots=None, flip_dir=None, flip_since=None,
         flip_score=None, log_path=LOG_PATH_DEFAULT, score_hist=None, flip_thr=20):
    """Call once per 5 s sample with data your app ALREADY fetched."""
    record_spot(state, now, spot_raw)
    record_change_oi(state, now, change_oi_resp, change_oi_error)
    report = freshness_report(state, now)
    if not state["initialized"]:
        _init_once(state, now, rev_alerts, flip_dir, flip_since, log_path)
    try:
        p2 = compute_phase2(state, now, rev_alerts, score_hist, flip_thr, report)
    except Exception as e:                      # Phase 2 must never break Phase 1
        p2 = {"color": "GREY", "label": f"PHASE 2 ERROR: {str(e)[:80]}", "error": True}
    state["p2"] = p2
    sync_alerts(state, now, rev_alerts, snapshots, flip_dir, flip_since, flip_score,
                report, log_path, p2=p2)
    process_outcomes(state, now, log_path)
    return report


# ------------------------------------------------------------------- display
def freshness_html(report, state):
    icon = {"FRESH": "🟢", "STALE": "🔴", "NEVER": "⚪", "NOT ENABLED": "⚫"}
    rows = []
    for kind, label in (("spot", "Spot"), ("oi", "Change-in-OI"), ("premium", "Option premium")):
        f = report["feeds"][kind]
        age = f"{f['age']:.0f}s ago" if f["age"] is not None else "—"
        last = f["last_success"].strftime("%H:%M:%S") if f["last_success"] else "—"
        err = f" · last error: {f['last_error']}" if f["last_error"] else ""
        rows.append(f"<div>{icon.get(f['status'], '⚪')} <b>{label}</b>: {f['status']} · last OK {last} "
                    f"({age}) · errors {f['errors']} · missing {f['missing']} · "
                    f"unchanged repeats {f['unchanged']}{err}</div>")
    color = "#2e7d32" if report["reliable"] else "#c62828"
    verdict = "DATA RELIABLE" if report["reliable"] else f"DATA NOT RELIABLE — {report['reason']}"
    log_note = (f"Shadow log: {state['logged']} lines written · pending outcomes {len(state['pending'])}"
                + (f" · ⚠️ log write errors {state['log_errors']}: {state['last_log_error']}"
                   if state["log_errors"] else ""))
    return (f'<div class="greeks-panel" style="border-left-color:{color};">'
            f'<b>🛰️ Smart OI Layer — Phase 1 (shadow) · {verdict}</b>'
            f'<div style="margin-top:6px; font-size:0.85rem;">{"".join(rows)}</div>'
            f'<div style="margin-top:6px; font-size:0.8rem; color:#555;">{log_note}</div></div>')


# =====================================================================
# PHASE 2 — Price confirmation (Module 1) + Sideways filter (Module 4)
# Display-only. Never changes the OI Flip score or any BUY/SELL signal.
# All thresholds are plain constants so they can be tuned from the log.
# =====================================================================
import math

PRICE_THR_PCT = {5: 0.04, 10: 0.06, 15: 0.08}   # min move (%) to count as directional
SPOT_REF_TOL_SEC = 30          # reference sample must be <=30 s before the target time
SPOT_CUR_MAX_AGE_SEC = 15      # current spot older than this = no price conclusion
SCORE_MAX_AGE_SEC = 90         # flip score older than this = not used
SCORE_REF_TOL_SEC = 120
FADE_DROP_POINTS = 5.0         # score change over FADE_WINDOW_MIN that counts as fading
FADE_WINDOW_MIN = 10
STRUCT_LOOKBACK_MIN = 15
SIDEWAYS_WINDOW_MIN = 20
MIN_VALID_CANDLES = 12         # of the last 20 one-minute candles
CANDLE_MIN_SAMPLES = 6         # a minute with <6 samples is a gap, never filled in
SW_EFFICIENCY_MAX = 0.35
SW_RANGE_PCT_MAX = 0.15
SW_SWING_BREAKS_MAX = 1
SW_MIN_FACTORS = 3            # of 5 factors

COLORS = {"GREEN": "#2e7d32", "YELLOW": "#f9a825", "ORANGE": "#ef6c00",
          "RED": "#c62828", "GREY": "#6e7781", "NEUTRAL": "#90a4ae"}


def _p2_fields(p2):
    p2 = p2 or {}
    return {"confirmation_status": p2.get("color", "SHADOW_NOT_EVALUATED"),
            "p2_label": p2.get("label"), "p2_price_dir": p2.get("price_dir"),
            "p2_sideways": p2.get("sideways_status"), "p2_oi_bias": p2.get("bias")}


def _sample_at_or_before(buf, target, tol_sec):
    best = None
    for s in buf:
        if s["ts"] <= target:
            best = s
        else:
            break
    if best and (target - best["ts"]).total_seconds() <= tol_sec:
        return best
    return None


def price_moves(state, now):
    """Nifty move over 5/10/15 min from recorded samples only. None = not enough history."""
    out = {"cur": None, "moves": {}, "pct": {}}
    buf = state["spot_buf"]
    if not buf:
        return out
    cur = buf[-1]
    if (now - cur["ts"]).total_seconds() > SPOT_CUR_MAX_AGE_SEC:
        return out
    out["cur"] = cur["spot"]
    for h in HORIZONS:
        ref = _sample_at_or_before(buf, now - timedelta(minutes=h), SPOT_REF_TOL_SEC)
        if ref:
            mv = cur["spot"] - ref["spot"]
            out["moves"][h], out["pct"][h] = mv, mv / ref["spot"] * 100
        else:
            out["moves"][h], out["pct"][h] = None, None
    return out


def price_direction(pct):
    avail = {h: v for h, v in pct.items() if v is not None}
    res = {"direction": "UNKNOWN", "strong": False, "signs": {}}
    if len(avail) < 2:
        return res
    signs = {h: (1 if v >= PRICE_THR_PCT[h] else (-1 if v <= -PRICE_THR_PCT[h] else 0))
             for h, v in avail.items()}
    total = sum(signs.values())
    res["signs"] = signs
    if total >= 2:
        res["direction"] = "RISING"
    elif total <= -2:
        res["direction"] = "FALLING"
    else:
        res["direction"] = "FLAT/MIXED"
    if res["direction"] in ("RISING", "FALLING"):
        sg = 1 if res["direction"] == "RISING" else -1
        p10 = avail.get(10)
        res["strong"] = (all(v == sg for v in signs.values()) and p10 is not None
                         and sg * p10 >= 2 * PRICE_THR_PCT[10])
    return res


def build_candles(buf, now, window_min):
    """Completed 1-minute candles only. Minutes with too few samples are skipped (gaps)."""
    cur_min = now.replace(second=0, microsecond=0)
    start = cur_min - timedelta(minutes=window_min)
    groups = {}
    for s in buf:
        k = s["ts"].replace(second=0, microsecond=0)
        if start <= k < cur_min:
            groups.setdefault(k, []).append(s["spot"])
    candles = []
    for k in sorted(groups):
        v = groups[k]
        if len(v) >= CANDLE_MIN_SAMPLES:
            candles.append({"t": k, "open": v[0], "high": max(v), "low": min(v), "close": v[-1]})
    return candles


def structure_levels(candles, now, cur):
    cut = now.replace(second=0, microsecond=0) - timedelta(minutes=STRUCT_LOOKBACK_MIN)
    c = [x for x in candles if x["t"] >= cut]
    if len(c) < 8 or cur is None:
        return {"ok": False}
    hi, lo = max(x["high"] for x in c), min(x["low"] for x in c)
    return {"ok": True, "hi": hi, "lo": lo, "above_high": cur > hi, "below_low": cur < lo}


def oi_bias(score, thr):
    if score is None:
        return "UNKNOWN"
    if score >= thr:
        return "BULLISH"
    if score <= -thr:
        return "BEARISH"
    return "WEAK"


def score_trend(score_hist, now):
    """Uses your existing meter history read-only. Stale score = not used."""
    if not score_hist:
        return {"score": None, "delta": None, "age": None}
    ts, sc = score_hist[-1]
    age = (now - ts).total_seconds()
    if age > SCORE_MAX_AGE_SEC:
        return {"score": None, "delta": None, "age": age}
    target = now - timedelta(minutes=FADE_WINDOW_MIN)
    ref = None
    for t, s in score_hist:
        if t <= target:
            ref = (t, s)
        else:
            break
    delta = (sc - ref[1]) if (ref and (target - ref[0]).total_seconds() <= SCORE_REF_TOL_SEC) else None
    return {"score": sc, "delta": delta, "age": age}


def _recent_alert_dirs(rev_alerts, now, minutes):
    dirs = set()
    for a in (rev_alerts or []):
        try:
            ts = _localize(datetime.strptime(a["ts"], "%Y-%m-%d %H:%M:%S"), now)
        except (KeyError, ValueError, TypeError):
            continue
        if 0 <= (now - ts).total_seconds() <= minutes * 60:
            d = _direction_from_type(a.get("type"))
            if d != "UNKNOWN":
                dirs.add(d)
    return dirs


def _count_rejections(candles, hi, lo):
    rng = hi - lo
    if rng <= 0:
        return 0, 0
    zone, mid = 0.15 * rng, (hi + lo) / 2
    top = bot = 0
    last_top = last_bot = -10
    for i, c in enumerate(candles):
        if c["high"] >= hi - zone and c["close"] <= mid and i - last_top >= 2:
            top += 1; last_top = i
        if c["low"] <= lo + zone and c["close"] >= mid and i - last_bot >= 2:
            bot += 1; last_bot = i
    return top, bot


def sideways_filter(candles, rev_alerts, now):
    res = {"status": "INSUFFICIENT", "valid": len(candles), "factors": [], "range_pts": None}
    if len(candles) < MIN_VALID_CANDLES:
        return res
    hi, lo = max(c["high"] for c in candles), min(c["low"] for c in candles)
    rng = hi - lo
    mid_price = (hi + lo) / 2
    rng_pct = rng / mid_price * 100
    eff = abs(candles[-1]["close"] - candles[0]["open"]) / rng if rng > 0 else 0.0
    breaks = 0
    for i in range(5, len(candles)):
        prior = candles[i - 5:i]
        if candles[i]["close"] > max(p["high"] for p in prior) or \
           candles[i]["close"] < min(p["low"] for p in prior):
            breaks += 1
    top, bot = _count_rejections(candles, hi, lo)
    dirs = _recent_alert_dirs(rev_alerts, now, SIDEWAYS_WINDOW_MIN)
    churn = ("BULLISH" in dirs and "BEARISH" in dirs and eff < 0.5)
    factors = [
        (f"Weak directional movement (efficiency {eff:.2f})", eff < SW_EFFICIENCY_MAX),
        (f"Narrow {SIDEWAYS_WINDOW_MIN}-min range ({rng:.0f} pts, {rng_pct:.2f}%)", rng_pct < SW_RANGE_PCT_MAX),
        (f"Few swing breaks ({breaks})", breaks <= SW_SWING_BREAKS_MAX),
        (f"Repeated rejection at range edges (top {top}, bottom {bot})", top >= 2 or bot >= 2),
        ("Bullish and bearish OI alerts alternating without sustained move", churn),
    ]
    n = sum(1 for _, ok in factors if ok)
    res.update({"status": "SIDEWAYS" if n >= SW_MIN_FACTORS else ("DIRECTIONAL" if n <= 1 else "TRANSITIONAL"),
                "factors": factors, "range_pts": rng, "true_count": n})
    return res


def classify(bias, pdir, reliable, reason):
    d, strong = pdir["direction"], pdir["strong"]
    if not reliable:
        return "GREY", f"INSUFFICIENT DATA — {reason}"
    if bias == "UNKNOWN":
        return "GREY", "INSUFFICIENT DATA — OI Flip score unavailable or stale"
    if d == "UNKNOWN":
        return "GREY", "INSUFFICIENT DATA — collecting price history (needs ~10 min)"
    if bias == "BULLISH":
        if d == "RISING":
            return "GREEN", "CONFIRMED BULLISH — OI AND PRICE AGREE"
        if d == "FALLING":
            return "ORANGE", "BULLISH OI / BEARISH PRICE — DIVERGENCE DETECTED."
        return "YELLOW", "BULLISH OI — PRICE NOT YET CONFIRMING"
    if bias == "BEARISH":
        if d == "FALLING":
            return "GREEN", "CONFIRMED BEARISH — OI AND PRICE AGREE"
        if d == "RISING":
            return "ORANGE", "BEARISH OI / BULLISH PRICE — DIVERGENCE DETECTED."
        return "YELLOW", "BEARISH OI — PRICE NOT YET CONFIRMING"
    # weak OI score
    if d == "RISING" and strong:
        return "YELLOW", "PRICE-LED BULLISH — WEAK OI SCORE, BULLISH PRICE CONFIRMS"
    if d == "FALLING" and strong:
        return "YELLOW", "PRICE-LED BEARISH — WEAK OI SCORE, BEARISH PRICE CONFIRMS"
    return "NEUTRAL", "NO CLEAR OI BIAS AND NO STRONG PRICE MOVE"


def compute_phase2(state, now, rev_alerts, score_hist, flip_thr, report):
    mv = price_moves(state, now)
    pdir = price_direction(mv["pct"]) if mv["cur"] is not None else \
        {"direction": "UNKNOWN", "strong": False, "signs": {}}
    tr = score_trend(score_hist, now)
    bias = oi_bias(tr["score"], flip_thr)
    fading = bool(tr["delta"] is not None and (
        (bias == "BULLISH" and tr["delta"] <= -FADE_DROP_POINTS) or
        (bias == "BEARISH" and tr["delta"] >= FADE_DROP_POINTS)))
    candles = build_candles(state["spot_buf"], now, SIDEWAYS_WINDOW_MIN)
    struct = structure_levels(candles, now, mv["cur"])
    sw = sideways_filter(candles, rev_alerts, now)
    color, label = classify(bias, pdir, report["reliable"], report["reason"])
    return {"color": color, "label": label, "bias": bias, "score": tr["score"],
            "score_delta": tr["delta"], "fading": fading, "price": mv["cur"],
            "moves": mv["moves"], "pct": mv["pct"], "price_dir": pdir["direction"],
            "strong": pdir["strong"], "structure": struct, "sideways_status": sw["status"],
            "sideways": sw, "candles": len(candles), "reason": report["reason"]}


def _mv_txt(mv, pct):
    return "—" if mv is None else f"{mv:+.1f} pts ({pct:+.2f}%)"


def phase2_html(state):
    p2 = state.get("p2")
    if not p2:
        return '<div class="greeks-panel" style="border-left-color:#6e7781;">Phase 2: waiting for first sample…</div>'
    color = COLORS.get(p2["color"], "#6e7781")
    if p2.get("error"):
        return (f'<div class="greeks-panel" style="border-left-color:{color};"><b>🧠 {p2["label"]}</b></div>')
    rows = []
    sc = p2["score"]
    sc_txt = f"{sc:+.0f}" if sc is not None else "—"
    d10 = p2["score_delta"]
    d_txt = f"{d10:+.0f} in {FADE_WINDOW_MIN} min" if d10 is not None else "trend needs 10 min of history"
    rows.append(f"<div>OI Flip score <b>{sc_txt}</b> ({p2['bias']}) · {d_txt}</div>")
    if p2["fading"]:
        rows.append('<div style="color:#c62828;"><b>⚠️ OI POSITIONING LOSING STRENGTH</b></div>')
    if p2["price"] is not None:
        m, pc = p2["moves"], p2["pct"]
        rows.append(f"<div>Nifty <b>{p2['price']:,.2f}</b> → <b>{p2['price_dir']}</b>"
                    f"{' (strong)' if p2['strong'] else ''}<br>"
                    f"5m {_mv_txt(m.get(5), pc.get(5))} · 10m {_mv_txt(m.get(10), pc.get(10))} · "
                    f"15m {_mv_txt(m.get(15), pc.get(15))}</div>")
    else:
        rows.append("<div>Nifty price: no fresh sample — no price conclusion</div>")
    stc = p2["structure"]
    if stc.get("ok"):
        if stc["above_high"]:
            rows.append(f"<div>Structure: spot is ABOVE the 15-min high ({stc['hi']:,.1f})</div>")
        elif stc["below_low"]:
            rows.append(f"<div>Structure: spot is BELOW the 15-min low ({stc['lo']:,.1f})</div>")
        else:
            rows.append(f"<div>Structure: inside 15-min range {stc['lo']:,.1f} – {stc['hi']:,.1f}</div>")
    sw = p2["sideways"]
    if sw["status"] == "INSUFFICIENT":
        rows.append(f"<div>Sideways check: collecting candles ({sw['valid']}/{MIN_VALID_CANDLES} valid)</div>")
    else:
        mark = "".join(f"<div style='font-size:0.78rem; color:#555;'>{'●' if ok else '○'} {t}</div>"
                       for t, ok in sw["factors"])
        warn = ('<div style="color:#c62828;"><b>⚠️ LOW DIRECTIONAL CONFIDENCE — SIDEWAYS CONDITIONS.</b></div>'
                if sw["status"] == "SIDEWAYS" else "")
        rows.append(f"<div>Sideways check: <b>{sw['status']}</b> ({sw['true_count']}/5 factors)</div>{warn}{mark}")
    return (f'<div class="greeks-panel" style="border-left-color:{color};">'
            f'<b>🧠 {p2["color"]} · {p2["label"]}</b>'
            f'<div style="margin-top:6px; font-size:0.85rem;">{"".join(rows)}</div>'
            f'<div style="margin-top:6px; font-size:0.75rem; color:#555;">Shadow mode — informational only. '
            f'Does not change the OI score or any BUY/SELL signal.</div></div>')
