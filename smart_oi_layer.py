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

import smart_oi_store as _store

LOG_PATH_DEFAULT = "smart_oi_log.jsonl"
SPOT_KEEP_SEC = 5400                      # keep 90 min of spot samples
STALE_AFTER = {"spot": 20, "oi": 30, "premium": 30}   # seconds since last SUCCESS
HORIZONS = (5, 10, 15)                    # minutes
OUTCOME_TOLERANCE_SEC = 90                # outcome sample must be within 90 s AFTER target
ALERT_SPOT_MAX_BACK_SEC = 15              # (kept for compatibility)
ALERT_SPOT_NEAR_SEC = 15                  # spot-at-alert = closest recorded sample within +-15 s
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


def spot_near(buf, ts, tol_sec=ALERT_SPOT_NEAR_SEC):
    """Closest recorded sample to the alert time (before OR just after), within tol_sec."""
    best, bd = None, None
    for s_ in buf:
        d = abs((s_["ts"] - ts).total_seconds())
        if d <= tol_sec and (bd is None or d < bd):
            best, bd = s_, d
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


def _p3_summary(evs):
    evs = sorted(evs, key=lambda e: e.get("ts", ""))
    pos = [e.get("stage") for e in evs if e.get("stage") in STAGE_RANK]
    peak = max(pos, key=lambda x: STAGE_RANK[x]) if pos else None
    inval = next((e.get("ts") for e in evs if e.get("status") == "INVALIDATED"), None)
    confirmed = next((e.get("ts") for e in evs if e.get("stage") == "CONFIRMED REVERSAL CANDIDATE"), None)
    ids = []
    for e in evs:
        for a in (e.get("alert_ids") or []):
            if a not in ids:
                ids.append(a)
    last = evs[-1]
    return {"p3_peak_stage": peak, "p3_final_stage": last.get("stage"),
            "p3_final_status": last.get("status"),
            "p3_max_confirm": max((e.get("confirm") or 0) for e in evs),
            "p3_n_valid": max((e.get("n_valid") or 0) for e in evs),
            "p3_invalidated_at": inval, "p3_confirmed_at": confirmed,
            "p3_max_adverse_pts": last.get("mae"), "p3_max_favorable_pts": last.get("mfe"),
            "p3_alert_ids": ";".join(ids)}


def load_log(path):
    """Merge append-only events into one record per alert. Bad lines are skipped."""
    alerts, outcomes, p3ev, bad = {}, {}, {}, 0
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
                t = r.get("type")
                if t == "alert":
                    alerts[r["id"]] = r
                elif t == "outcome":
                    outcomes.setdefault(r["id"], {})[r["h"]] = r
                elif t == "p3":
                    p3ev.setdefault(r["id"], []).append(r)
    except OSError:
        return [], 0
    by_id = {}
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
        by_id[aid] = rec
    for sid, evs in p3ev.items():
        if sid in by_id:
            summ = _p3_summary(evs)
            by_id[sid].update(summ)
            by_id[sid]["p3_setup_id"] = sid
            for oid in [x for x in summ["p3_alert_ids"].split(";") if x]:
                if oid in by_id and oid != sid and not by_id[oid].get("p3_setup_id"):
                    by_id[oid].update(summ)
                    by_id[oid]["p3_setup_id"] = sid
    return list(by_id.values()), bad


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
        sp = spot_near(state["spot_buf"], ts)
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
            sp = spot_near(state["spot_buf"], flip_since)
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
         flip_score=None, log_path=LOG_PATH_DEFAULT, score_hist=None, flip_thr=20,
         rev_scorer=None, gh_cfg=None):
    """Call once per 5 s sample with data your app ALREADY fetched."""
    record_spot(state, now, spot_raw)
    record_change_oi(state, now, change_oi_resp, change_oi_error)
    report = freshness_report(state, now)
    state["last_report"] = report
    if not state["initialized"]:
        _init_once(state, now, rev_alerts, flip_dir, flip_since, log_path)
    state.setdefault("p3", _new_p3())
    state.setdefault("gh", _store.new_gh_state())
    try:
        p2 = compute_phase2(state, now, rev_alerts, score_hist, flip_thr, report)
    except Exception as e:                      # Phase 2 must never break Phase 1
        p2 = {"color": "GREY", "label": f"PHASE 2 ERROR: {str(e)[:80]}", "error": True}
    state["p2"] = p2
    try:
        p3_update(state, now, report, p2, snapshots, rev_scorer, rev_alerts, log_path)
        state["p3_error"] = None
    except Exception as e:                      # Phase 3 must never break anything else
        state["p3_error"] = f"{type(e).__name__}: {str(e)[:80]}"
    sync_alerts(state, now, rev_alerts, snapshots, flip_dir, flip_since, flip_score,
                report, log_path, p2=p2)
    process_outcomes(state, now, log_path)
    try:
        _store.sync(state["gh"], now, gh_cfg, lambda: load_log(log_path)[0], state["logged"])
    except Exception as e:
        state["gh"]["last_error"] = type(e).__name__
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
    gh = state.get("gh") or {}
    if gh.get("configured"):
        if gh.get("last_error"):
            gh_note = (f"☁️ GitHub log: ⚠️ last save failed ({gh['last_error']})"
                       + (f" · last OK {gh['last_ok'].strftime('%H:%M:%S')}" if gh.get("last_ok") else ""))
        elif gh.get("last_ok"):
            gh_note = f"☁️ GitHub log: saved ✔ {gh['last_ok'].strftime('%H:%M:%S')} · {gh['pushes']} saves"
        else:
            gh_note = "☁️ GitHub log: connected — waiting for first alert to save"
    else:
        gh_note = "☁️ GitHub log: NOT configured — local log is temporary (lost on redeploy)"
    log_note = (f"{gh_note}<br>Shadow log: {state['logged']} lines written · pending outcomes {len(state['pending'])}"
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


SW60_WINDOW_MIN = 60
SW60_MIN_CANDLES = 30          # of the last 60 one-minute candles
SW60_EFFICIENCY_MAX = 0.35
SW60_RANGE_PCT_MAX = 0.35
SW60_ALERT_WINDOW_MIN = 90
SW60_ALERTS_MIN = 3            # Reversal-Meter alerts in 90 min, both directions = churn
SW60_MIN_FACTORS = 2           # of 3


def _alerts_in_window(rev_alerts, now, minutes):
    out = []
    for a in (rev_alerts or []):
        try:
            ts = _localize(datetime.strptime(a["ts"], "%Y-%m-%d %H:%M:%S"), now)
        except (KeyError, ValueError, TypeError):
            continue
        if 0 <= (now - ts).total_seconds() <= minutes * 60:
            out.append((ts, _direction_from_type(a.get("type"))))
    return out


def range_filter_60(candles, rev_alerts, now):
    """Longer-horizon chop detector: catches days that look directional in any 20-min
    window but keep reversing. Needs 30+ valid minutes; otherwise says so."""
    alerts = _alerts_in_window(rev_alerts, now, SW60_ALERT_WINDOW_MIN)
    dirs = {d for _, d in alerts if d != "UNKNOWN"}
    churn = len(alerts) >= SW60_ALERTS_MIN and len(dirs) >= 2
    res = {"status": "INSUFFICIENT", "valid": len(candles), "factors": [],
           "alerts_90": len(alerts), "churn": churn}
    if len(candles) < SW60_MIN_CANDLES:
        return res
    hi, lo = max(c["high"] for c in candles), min(c["low"] for c in candles)
    rng = hi - lo
    rng_pct = rng / ((hi + lo) / 2) * 100
    eff = abs(candles[-1]["close"] - candles[0]["open"]) / rng if rng > 0 else 0.0
    factors = [
        (f"60-min directional efficiency {eff:.2f}", eff < SW60_EFFICIENCY_MAX),
        (f"60-min range {rng:.0f} pts ({rng_pct:.2f}%)", rng_pct < SW60_RANGE_PCT_MAX),
        (f"{len(alerts)} Reversal-Meter alert(s) in last {SW60_ALERT_WINDOW_MIN} min, both directions", churn),
    ]
    n = sum(1 for _, ok in factors if ok)
    res.update({"status": "RANGE-BOUND" if n >= SW60_MIN_FACTORS else "NOT RANGE-BOUND",
                "factors": factors, "true_count": n})
    return res


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
    sw60 = range_filter_60(build_candles(state["spot_buf"], now, SW60_WINDOW_MIN), rev_alerts, now)
    if sw["status"] == "SIDEWAYS" or sw60["status"] == "RANGE-BOUND":
        combined = "SIDEWAYS"
    elif sw["status"] == "INSUFFICIENT":
        combined = "INSUFFICIENT"
    else:
        combined = sw["status"]
    color, label = classify(bias, pdir, report["reliable"], report["reason"])
    return {"color": color, "label": label, "bias": bias, "score": tr["score"],
            "score_delta": tr["delta"], "fading": fading, "price": mv["cur"],
            "moves": mv["moves"], "pct": mv["pct"], "price_dir": pdir["direction"],
            "strong": pdir["strong"], "structure": struct, "sideways_status": combined,
            "sideways": sw, "sideways60": sw60, "market_open": report["market_open"],
            "candles": len(candles), "reason": report["reason"]}


def _mv_txt(mv, pct):
    return "—" if mv is None else f"{mv:+.1f} pts ({pct:+.2f}%)"


def phase2_html(state):
    p2 = state.get("p2")
    if not p2:
        return '<div class="greeks-panel" style="border-left-color:#6e7781;">Phase 2: waiting for first sample…</div>'
    color = COLORS.get(p2["color"], "#6e7781")
    if p2.get("error"):
        return (f'<div class="greeks-panel" style="border-left-color:{color};"><b>🧠 {p2["label"]}</b></div>')
    foot = ('<div style="margin-top:6px; font-size:0.75rem; color:#555;">Shadow mode — informational only. '
            'Does not change the OI score or any BUY/SELL signal.</div>')
    if not p2.get("market_open", True):
        return (f'<div class="greeks-panel" style="border-left-color:{color};">'
                f'<b>🧠 {p2["color"]} · {p2["label"]}</b>'
                f'<div style="margin-top:6px; font-size:0.85rem;">Price checks are paused while the market is closed.</div>{foot}</div>')
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
    if p2["sideways_status"] == "SIDEWAYS":
        rows.append('<div style="color:#c62828;"><b>⚠️ LOW DIRECTIONAL CONFIDENCE — SIDEWAYS CONDITIONS.</b></div>')
    small = "font-size:0.78rem; color:#555;"
    sw = p2["sideways"]
    if sw["status"] == "INSUFFICIENT":
        rows.append(f"<div>20-min sideways check: collecting candles ({sw['valid']}/{MIN_VALID_CANDLES} valid)</div>")
    else:
        rows.append(f"<div>20-min sideways check: <b>{sw['status']}</b> ({sw['true_count']}/5 factors)</div>"
                    + "".join(f"<div style='{small}'>{'●' if ok else '○'} {t}</div>" for t, ok in sw["factors"]))
    s60 = p2.get("sideways60") or {}
    if s60.get("status") == "INSUFFICIENT":
        rows.append(f"<div>60-min range check: collecting candles ({s60.get('valid', 0)}/{SW60_MIN_CANDLES} valid) · "
                    f"{s60.get('alerts_90', 0)} alert(s) in last {SW60_ALERT_WINDOW_MIN} min</div>")
    elif s60:
        warn = ('<div style="color:#c62828;"><b>⚠️ RANGE-BOUND (60 MIN) — REPEATED REVERSALS ARE LOW CONFIDENCE.</b></div>'
                if s60["status"] == "RANGE-BOUND" else "")
        rows.append(f"<div>60-min range check: <b>{s60['status']}</b> ({s60['true_count']}/3 factors)</div>{warn}"
                    + "".join(f"<div style='{small}'>{'●' if ok else '○'} {t}</div>" for t, ok in s60["factors"]))
    return (f'<div class="greeks-panel" style="border-left-color:{color};">'
            f'<b>🧠 {p2["color"]} · {p2["label"]}</b>'
            f'<div style="margin-top:6px; font-size:0.85rem;">{"".join(rows)}</div>{foot}</div>')


# =====================================================================
# PHASE 3 (v2) — Reversal confirmation: every alert is WATCHED for 15 minutes
# and judged by what price does. The OI spike fading no longer ends the watch
# (the original meter's anomalies are one-shot by design).
#   CONFIRMED   price agreed (>=3 of 5 tests) and did not invalidate
#   FADED       was confirmed, then confirmation weakened before the window ended
#   INVALIDATED Nifty moved against the alert and stayed there
#   EXPIRED     15 minutes passed without price confirmation
# Reads your existing reversal scores through a callback. Never changes them.
# =====================================================================
P3_VALID_SCORE = 60            # same bar your Reversal Meter uses for an alert
P3_WATCH_MIN = 15              # every alert is watched this long
P3_CONFIRM_MIN = 3             # price tests (of 5) needed to confirm
P3_CONFIRM_MIN_AGE_SEC = 120   # cannot confirm in the first 2 minutes
P3_MAX_SNAP_AGE_SEC = 30       # an OI sample older than this at processing time is skipped
P3_REC_PCT = 0.03              # spot must move >=0.03% in the alert direction ("recovery")
P3_INVALID_PCT = 0.08          # opposite move (~19 pts at 23,800) ...
P3_INVAL_HOLD_SEC = 30         # ... held this long = INVALIDATED
P3_WARN_ADVERSE_FRAC = 0.5     # half of the invalidation move = warning
P3_OPPOSITE_WINDOW_MIN = 10
P3_OI_SUPPORT_MIN = 5.0        # OI Flip score must lean the same way by at least this
P3_WEAKEN_DROP = 2             # confirmations dropping by this much = losing strength
P3_KEEP_SETUPS = 60
P3_CLOSED_SHOW_MIN = 15        # closed cards stay visible this long

POS_STAGES = ["INITIAL DETECTION", "DEVELOPING REVERSAL", "SUSTAINED REVERSAL",
              "CONFIRMED REVERSAL CANDIDATE"]
STAGE_RANK = {s_: i + 1 for i, s_ in enumerate(POS_STAGES)}


def _new_p3():
    return {"last_snap_ts": None, "last_hash": None, "setups": {}, "order": [],
            "active": {"BULLISH": None, "BEARISH": None}, "skipped": 0, "scorer_errors": 0}


def _fmt_oi(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    a = abs(v)
    sign = "+" if v > 0 else ("−" if v < 0 else "")
    if a >= 1e7: return f"{sign}{a/1e7:.2f} Cr"
    if a >= 1e5: return f"{sign}{a/1e5:.2f} L"
    if a >= 1e3: return f"{sign}{a/1e3:.1f} K"
    return f"{sign}{a:.0f}"


def _pivots(candles, key):
    out = []
    for i in range(2, len(candles) - 2):
        v = candles[i][key]
        nb = [candles[i + k][key] for k in (-2, -1, 1, 2)]
        if key == "high" and all(v > x for x in nb):
            out.append((i, v))
        if key == "low" and all(v < x for x in nb):
            out.append((i, v))
    return out


def _p3_price_tests(setup, cur, mv, candles, p2):
    """Five separate tests. True / False / None (None = cannot be evaluated, never guessed)."""
    bull = setup["dir"] == "BULLISH"
    d = 1 if bull else -1
    names = (["Spot recovery", "Higher low formed", "Broke above swing high",
              "Positive momentum", "OI Flip score supports"] if bull else
             ["Spot weakness", "Lower high formed", "Broke below swing low",
              "Negative momentum", "OI Flip score supports"])
    tests = []
    move_pct = d * (cur - setup["start_spot"]) / setup["start_spot"] * 100
    tests.append((names[0], move_pct >= P3_REC_PCT, f"{cur - setup['start_spot']:+.1f} pts since alert"))
    pv = _pivots(candles, "low" if bull else "high")
    if len(pv) >= 2:
        ok = pv[-1][1] > pv[-2][1] if bull else pv[-1][1] < pv[-2][1]
        tests.append((names[1], ok, f"{pv[-2][1]:,.1f} → {pv[-1][1]:,.1f}"))
    else:
        tests.append((names[1], None, "not enough swing points yet"))
    pb = _pivots(candles, "high" if bull else "low")
    if pb and candles:
        lvl = pb[-1][1]
        close = candles[-1]["close"]
        ok = close > lvl if bull else close < lvl
        tests.append((names[2], ok, f"last candle close {close:,.1f} vs swing {lvl:,.1f}"))
    else:
        tests.append((names[2], None, "no swing level yet"))
    p5, p10 = mv["pct"].get(5), mv["pct"].get(10)
    if p5 is None or p10 is None:
        tests.append((names[3], None, "needs 10 min of price history"))
    else:
        tests.append((names[3], d * p5 >= PRICE_THR_PCT[5] and d * p10 > 0,
                      f"5m {p5:+.2f}% · 10m {p10:+.2f}%"))
    sc = (p2 or {}).get("score")
    if sc is None:
        tests.append((names[4], None, "OI Flip score unavailable"))
    else:
        tests.append((names[4], (sc >= P3_OI_SUPPORT_MIN) if bull else (sc <= -P3_OI_SUPPORT_MIN),
                      f"score {sc:+.0f}"))
    return tests


def _p3_log_event(state, path, now, s):
    key = (s["stage"], s["status"], s["color"], s["count"], s["run_max"],
           len(s["alert_ids"]), bool(s["confirmed_at"]))
    if s["logged_key"] == key:
        return
    s["logged_key"] = key
    _append(state, path, {"type": "p3", "id": s["id"], "ts": now.isoformat(), "stage": s["stage"],
                          "status": s["status"], "color": s["color"], "confirm": s["count"],
                          "n_valid": s["run_max"], "alert_ids": list(s["alert_ids"]),
                          "warnings": list(s["warnings"])[:4],
                          "mae": round(s["mae"], 1), "mfe": round(s["mfe"], 1)})


_CLOSE = {"INVALIDATED": ("INVALIDATED", "RED", "INVALIDATED — OPPOSITE PRICE MOVEMENT."),
          "CONFIRMED": ("CONFIRMED REVERSAL CANDIDATE", "GREEN",
                        "CONFIRMED — price agreed with the alert within the watch window."),
          "FADED": ("REVERSAL LOSING STRENGTH", "ORANGE",
                    "REVERSAL LOSING STRENGTH — confirmation faded before the window ended."),
          "EXPIRED": ("EXPIRED", "NEUTRAL", "EXPIRED — no price confirmation within the watch window.")}


def _p3_close(state, now, s, status, path):
    p3 = state["p3"]
    if status == "CONFIRMED" and s.get("losing"):
        status = "FADED"
    s["status"], s["closed_at"] = status, now
    s["stage"], s["color"], s["label"] = _CLOSE[status]
    if status == "INVALIDATED":
        s["invalidated_at"] = now
    if p3["active"].get(s["dir"]) == s["id"]:
        p3["active"][s["dir"]] = None
    _p3_log_event(state, path, now, s)


def _p3_start(state, now, direction, snap, score, an, cur, p2, path):
    p3 = state["p3"]
    sid = f"{snap['ts'].strftime('%Y-%m-%d %H:%M:%S')}|p3_{direction}"
    if sid in p3["setups"]:
        return p3["setups"][sid]
    s = {"id": sid, "dir": direction, "start_ts": snap["ts"], "start_spot": cur,
         "run": 1, "run_max": 1, "fail_streak": 0, "oi_faded": False, "samples": 1,
         "peak_score": score, "last_score": score,
         "stage": "INITIAL DETECTION", "status": "ACTIVE", "color": "YELLOW",
         "peak_stage": "INITIAL DETECTION",
         "ce": snap.get("ce"), "pe": snap.get("pe"), "oi_reason": "; ".join((an.get("reasons") or [])[:2]),
         "conflict": False, "opp_flag": False, "alert_ids": [], "max_confirm": 0,
         "count": 0, "evaluable": 0, "tests": [], "warnings": [], "inval_since": None,
         "closed_at": None, "invalidated_at": None, "confirmed_at": None, "losing": False,
         "mae": 0.0, "mfe": 0.0, "label": "INITIAL DETECTION — OI reversal seen, awaiting price confirmation",
         "reason": "", "logged_key": None, "stale": False, "cur": cur, "adverse": 0.0}
    p3["setups"][sid] = s
    p3["order"].append(sid)
    p3["active"][direction] = sid
    _log_alert(state, path, now, {
        "type": "alert", "id": sid, "ts": snap["ts"].isoformat(), "source": "p3_setup",
        "direction": direction, "spot_at_alert": cur, "oi_flip_score": (p2 or {}).get("score"),
        "call_oi_change": snap.get("ce"), "put_oi_change": snap.get("pe"),
        **_p2_fields(p2), "confirmation_status": "YELLOW", "data_reliable": True,
        "msg": f"P3 {direction} reversal setup, reversal score {score:.0f}"})
    if len(p3["order"]) > P3_KEEP_SETUPS:
        for old in list(p3["order"]):
            if p3["setups"][old]["status"] != "ACTIVE":
                p3["order"].remove(old)
                p3["setups"].pop(old, None)
                break
    return s


def _p3_on_snapshot(state, now, snap, an, bs, ls, cur, p2, path):
    """A new fresh OI sample. It can start or extend a watch; a faded spike never ends one."""
    p3 = state["p3"]
    conflict = bool((an.get("ce_build") and an.get("pe_build")) or
                    (an.get("ce_unwind") and an.get("pe_unwind")))
    for direction, score, gate in (("BULLISH", ls, an.get("pe_unwind") or an.get("ce_build")),
                                   ("BEARISH", bs, an.get("ce_unwind") or an.get("pe_build"))):
        valid = bool(score >= P3_VALID_SCORE and gate)
        sid = p3["active"][direction]
        s = p3["setups"].get(sid) if sid else None
        if valid:
            if s is None:
                if cur is None:
                    p3["skipped"] += 1
                    continue
                s = _p3_start(state, now, direction, snap, score, an, cur, p2, path)
            else:
                s["run"] = s["run"] + 1 if s["fail_streak"] == 0 else 1
                s["fail_streak"] = 0
                s["samples"] += 1
            s["run_max"] = max(s["run_max"], s["run"])
            s.update(last_score=score, ce=snap.get("ce"), pe=snap.get("pe"), conflict=conflict,
                     oi_reason="; ".join((an.get("reasons") or [])[:2]))
            s["peak_score"] = max(s["peak_score"], score)
            other = p3["active"]["BEARISH" if direction == "BULLISH" else "BULLISH"]
            if other:
                o = p3["setups"][other]
                if (snap["ts"] - o["start_ts"]).total_seconds() <= P3_OPPOSITE_WINDOW_MIN * 60:
                    o["opp_flag"] = True
        elif s is not None and s["status"] == "ACTIVE":
            s["fail_streak"] += 1
            s["run"], s["oi_faded"] = 0, True
            s["last_score"], s["conflict"] = score, conflict


def _p3_link_alerts(s, rev_alerts):
    for a in (rev_alerts or []):
        if _direction_from_type(a.get("type")) != s["dir"]:
            continue
        aid = f"{a.get('ts')}|{a.get('type')}"
        if aid in s["alert_ids"]:
            continue
        try:
            ts = _localize(datetime.strptime(a["ts"], "%Y-%m-%d %H:%M:%S"), s["start_ts"])
        except (KeyError, ValueError, TypeError):
            continue
        if (ts - s["start_ts"]).total_seconds() >= -60:
            s["alert_ids"].append(aid)


def _p3_evaluate(state, now, report, p2, mv, candles, rev_alerts, path):
    p3, cur = state["p3"], mv["cur"]
    for sid in [x for x in p3["active"].values() if x]:
        s = p3["setups"][sid]
        _p3_link_alerts(s, rev_alerts)
        age = (now - s["start_ts"]).total_seconds()
        if age >= P3_WATCH_MIN * 60:                       # watch window over -> final verdict
            _p3_close(state, now, s, "CONFIRMED" if s["confirmed_at"] else "EXPIRED", path)
            continue
        if not report["reliable"] or cur is None:          # never confirm / invalidate on stale data
            s["stale"], s["color"] = True, "GREY"
            s["label"] = "INSUFFICIENT DATA — " + (report["reason"] if not report["reliable"] else "no fresh spot")
            continue
        s["stale"], s["cur"] = False, cur
        d = 1 if s["dir"] == "BULLISH" else -1
        tests = _p3_price_tests(s, cur, mv, candles, p2)
        s["tests"] = tests
        s["count"] = sum(1 for _, ok, _ in tests if ok is True)
        s["evaluable"] = sum(1 for _, ok, _ in tests if ok is not None)
        s["max_confirm"] = max(s["max_confirm"], s["count"])
        move_pts = d * (cur - s["start_spot"])
        s["mfe"], s["mae"] = max(s["mfe"], move_pts), max(s["mae"], -move_pts)
        adverse = -move_pts / s["start_spot"] * 100
        s["adverse"] = adverse
        if adverse >= P3_INVALID_PCT:
            s["inval_since"] = s["inval_since"] or now
            if (now - s["inval_since"]).total_seconds() >= P3_INVAL_HOLD_SEC:
                _p3_close(state, now, s, "INVALIDATED", path)
                continue
        else:
            s["inval_since"] = None
        if s["confirmed_at"] is None and s["count"] >= P3_CONFIRM_MIN and age >= P3_CONFIRM_MIN_AGE_SEC:
            s["confirmed_at"] = now
        near_invalid = adverse >= P3_INVALID_PCT * P3_WARN_ADVERSE_FRAC
        s["losing"] = bool(((s["max_confirm"] - s["count"]) >= P3_WEAKEN_DROP and s["max_confirm"] >= 2)
                           or near_invalid)
        if s["losing"]:
            stage = "REVERSAL LOSING STRENGTH"
        elif s["confirmed_at"]:
            stage = "CONFIRMED REVERSAL CANDIDATE"
        elif s["run_max"] >= 3:
            stage = "SUSTAINED REVERSAL"
        elif s["run_max"] == 2:
            stage = "DEVELOPING REVERSAL"
        else:
            stage = "INITIAL DETECTION"
        s["stage"] = stage
        if stage in STAGE_RANK and STAGE_RANK[stage] > STAGE_RANK.get(s["peak_stage"], 0):
            s["peak_stage"] = stage
        sideways = (p2 or {}).get("sideways_status") == "SIDEWAYS"
        warns = []
        if age >= 180 and s["evaluable"] >= 3 and s["count"] <= 1:
            warns.append("OI changed but price is NOT confirming")
        if s["opp_flag"]:
            warns.append("OI flipped direction shortly after this alert")
        if s["conflict"]:
            warns.append("Call and Put OI show conflicting behaviour")
        if sideways:
            warns.append("LOW DIRECTIONAL CONFIDENCE — SIDEWAYS CONDITIONS.")
        if s["oi_faded"] and s["count"] < P3_CONFIRM_MIN and age >= 180:
            warns.append("OI movement looks temporary")
        if near_invalid:
            warns.append(f"Spot is moving against this setup ({-move_pts:.0f} pts)")
        s["warnings"] = warns
        if s["losing"]:
            s["color"] = "ORANGE"
            s["label"] = ("REVERSAL LOSING STRENGTH — PRICE MOVING AGAINST THE ALERT." if near_invalid
                          else "REVERSAL LOSING STRENGTH.")
        elif stage == "CONFIRMED REVERSAL CANDIDATE":
            s["color"] = "YELLOW" if sideways else "GREEN"
            s["label"] = stage + (" (sideways — treat with caution)" if sideways else " — PRICE AGREES WITH THE ALERT")
        else:
            s["color"] = "YELLOW"
            s["label"] = {"INITIAL DETECTION": "INITIAL DETECTION — awaiting price confirmation",
                          "DEVELOPING REVERSAL": "DEVELOPING REVERSAL — OI repeated, awaiting price confirmation",
                          "SUSTAINED REVERSAL": f"SUSTAINED REVERSAL — price confirmation {s['count']}/{P3_CONFIRM_MIN} needed"}[stage]
        s["reason"] = (f"Watching {age / 60:.0f}/{P3_WATCH_MIN} min · best run of OI samples {s['run_max']} · "
                       f"price tests {s['count']}/{s['evaluable']} passing (need {P3_CONFIRM_MIN})")
        _p3_log_event(state, path, now, s)


def p3_update(state, now, report, p2, snapshots, rev_scorer, rev_alerts, path):
    p3 = state["p3"]
    mv = price_moves(state, now)
    candles = build_candles(state["spot_buf"], now, SIDEWAYS_WINDOW_MIN)
    if rev_scorer and snapshots:
        for idx, snap in enumerate(snapshots):
            if p3["last_snap_ts"] is not None and snap["ts"] <= p3["last_snap_ts"]:
                continue
            p3["last_snap_ts"] = snap["ts"]
            h = snap.get("hash")
            if h is not None and h == p3["last_hash"]:
                continue                                   # duplicate OI data is never a new sample
            p3["last_hash"] = h
            if (now - snap["ts"]).total_seconds() > P3_MAX_SNAP_AGE_SEC or not report["reliable"]:
                p3["skipped"] += 1                         # stale / unreliable: not counted
                continue
            try:
                an, bs, ls = rev_scorer(snapshots[:idx + 1])
            except Exception:
                p3["scorer_errors"] += 1
                continue
            _p3_on_snapshot(state, now, snap, an, bs, ls, mv["cur"], p2, path)
    _p3_evaluate(state, now, report, p2, mv, candles, rev_alerts, path)


def _p3_card(s, now):
    color = COLORS.get(s["color"], "#6e7781")
    closed = s["status"] != "ACTIVE"
    tick_ = {True: "✅", False: "❌", None: "⚪"}
    tests = " · ".join(f"{tick_[ok]} {n}" for n, ok, _ in s["tests"]) if s["tests"] else "not evaluated yet"
    mv_txt = f"{s['cur'] - s['start_spot']:+.1f} pts" if s.get("cur") else "—"
    warn = "".join(f"<div style='color:#c62828;'>⚠️ {w}</div>" for w in s["warnings"] if not closed)
    when = (f"closed — worst move against {s['mae']:.0f} pts, best move for {s['mfe']:.0f} pts" if closed else
            f"watching {min(P3_WATCH_MIN, (now - s['start_ts']).total_seconds() / 60):.0f}/{P3_WATCH_MIN} min")
    faded = (" · OI spike has faded (normal — judged on price)" if s["oi_faded"] and not closed else "")
    return (f'<div class="greeks-panel" style="border-left-color:{color}; margin-bottom:8px;">'
            f'<b>{s["color"]} · {s["dir"]} REVERSAL — {s["label"]}</b>'
            f'<div style="margin-top:6px; font-size:0.85rem;">'
            f'<div>Alert time: <b>{s["start_ts"].strftime("%H:%M:%S")}</b> · Nifty at alert {s["start_spot"]:,.1f} · '
            f'{when} · linked Reversal-Meter alerts: {len(s["alert_ids"])}</div>'
            f'<div>OI behaviour: reversal score <b>{s["last_score"]:.0f}</b> (peak {s["peak_score"]:.0f}) · '
            f'CE ΔOI {_fmt_oi(s["ce"])} · PE ΔOI {_fmt_oi(s["pe"])}{faded}'
            f'{" · " + s["oi_reason"] if s["oi_reason"] else ""}</div>'
            f'<div>Nifty behaviour since alert: <b>{mv_txt}</b></div>'
            f'<div>Price confirmation: <b>{s["count"]}/{s["evaluable"]}</b> evaluable (need {P3_CONFIRM_MIN}) — {tests}</div>'
            f'<div style="color:#555;">{s["reason"]}</div>{warn}</div></div>')


def phase3_html(state, now):
    p3 = state.get("p3")
    if state.get("p3_error"):
        return (f'<div class="greeks-panel" style="border-left-color:#6e7781;">'
                f'Phase 3 error (other features unaffected): {state["p3_error"]}</div>')
    if not p3 or not p3["order"]:
        return ('<div class="greeks-panel" style="border-left-color:#6e7781;">'
                '<b>🔄 No reversal setups yet this session.</b><div style="font-size:0.8rem; color:#555;">'
                f'Every alert from your Reversal Meter is watched for {P3_WATCH_MIN} minutes and judged on price. '
                'Shadow mode — informational only.</div></div>')
    rep = state.get("last_report")
    setups = [p3["setups"][x] for x in p3["order"]]
    tally = {k: sum(1 for x in setups if x["status"] == k)
             for k in ("ACTIVE", "CONFIRMED", "FADED", "INVALIDATED", "EXPIRED")}
    score = (f'<div style="font-size:0.85rem; margin-bottom:6px;"><b>This session:</b> {len(setups)} alert(s) watched · '
             f'{tally["CONFIRMED"]} confirmed · {tally["FADED"]} faded · {tally["INVALIDATED"]} invalidated · '
             f'{tally["EXPIRED"]} expired without confirmation · {tally["ACTIVE"]} still being watched</div>')
    cards, shown = [], 0
    for s in reversed(setups):
        recent_closed = s["closed_at"] is not None and (now - s["closed_at"]).total_seconds() <= P3_CLOSED_SHOW_MIN * 60
        if s["status"] == "ACTIVE" or recent_closed:
            cards.append(_p3_card(s, now))
            shown += 1
        if shown >= 3:
            break
    fresh = ""
    if rep:
        sp, oi = rep["feeds"]["spot"], rep["feeds"]["oi"]
        age = lambda f: f"{f['age']:.0f}s" if f["age"] is not None else "—"
        fresh = (f'<div style="font-size:0.78rem; color:#555;">Data freshness: spot {sp["status"]} ({age(sp)}) · '
                 f'OI {oi["status"]} ({age(oi)}) · samples skipped as stale/duplicate: {p3["skipped"]}</div>')
    hist = "".join(
        f"<div style='font-size:0.78rem;'>{x['start_ts'].strftime('%H:%M')} · {x['dir']} · "
        f"<b>{x['status']}</b> · price tests best {x['max_confirm']}/5 · "
        f"worst move against {x['mae']:.0f} pts, best for {x['mfe']:.0f} pts</div>"
        for x in reversed(setups[-8:]))
    return (score + "".join(cards) + fresh +
            f'<div style="margin-top:6px;"><b style="font-size:0.8rem;">History (kept, never deleted)</b>{hist}</div>'
            '<div style="font-size:0.75rem; color:#555; margin-top:4px;">Shadow mode — informational only. '
            'Does not change your Reversal Meter, alerts or BUY/SELL signals.</div>')
