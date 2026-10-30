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
                report, path):
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
            "confirmation_status": "SHADOW_NOT_EVALUATED",
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
                "confirmation_status": "SHADOW_NOT_EVALUATED",
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
         flip_score=None, log_path=LOG_PATH_DEFAULT):
    """Call once per 5 s sample with data your app ALREADY fetched."""
    record_spot(state, now, spot_raw)
    record_change_oi(state, now, change_oi_resp, change_oi_error)
    report = freshness_report(state, now)
    if not state["initialized"]:
        _init_once(state, now, rev_alerts, flip_dir, flip_since, log_path)
    sync_alerts(state, now, rev_alerts, snapshots, flip_dir, flip_since, flip_score,
                report, log_path)
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
