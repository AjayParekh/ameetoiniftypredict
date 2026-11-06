"""
smart_oi_store.py — permanent alert log in a separate private GitHub repository.

* No Streamlit import. Uses only `requests` (already in your requirements.txt).
* One CSV per day:  alerts/YYYY-MM-DD_alerts.csv  (opens directly in Excel).
* Nothing is ever deleted: rows already in GitHub are merged with new local rows.
* Pushes run in a background thread and are throttled, so the dashboard never waits.
* The token is read by the caller from Streamlit secrets and is never logged or shown.
"""
import base64
import csv
import hashlib
import io
import threading

import requests

GH_API = "https://api.github.com"
GH_MIN_INTERVAL_SEC = 60
HTTP_TIMEOUT = 8

COLUMNS = [
    "id", "ts", "source", "direction", "spot_at_alert", "oi_flip_score",
    "call_oi_change", "put_oi_change", "confirmation_status",
    "p2_label", "p2_price_dir", "p2_sideways", "p2_oi_bias", "data_reliable",
    "price_5m", "price_10m", "price_15m", "hit_5m", "hit_10m", "hit_15m",
    "p3_setup_id", "p3_peak_stage", "p3_final_stage", "p3_final_status",
    "p3_max_confirm", "p3_n_valid", "p3_confirmed_at", "p3_invalidated_at",
    "p3_max_adverse_pts", "p3_max_favorable_pts", "p3_alert_ids", "spot_src", "msg",
]


# ------------------------------------------------------------ http (patchable)
def _http_get(url, headers, params=None):
    return requests.get(url, headers=headers, params=params, timeout=HTTP_TIMEOUT)


def _http_put(url, headers, payload):
    return requests.put(url, headers=headers, json=payload, timeout=HTTP_TIMEOUT)


def new_gh_state():
    return {"configured": False, "busy": False, "last_push": None, "last_ok": None,
            "last_error": None, "pushes": 0, "pushed_logged": -1, "cache": {}, "hashes": {}}


# --------------------------------------------------------------- CSV helpers
def _cell(v):
    if v is None:
        return ""
    return str(v)


def records_to_rows(records):
    rows = []
    for r in records:
        row = {c: _cell(r.get(c)) for c in COLUMNS}
        if not row["id"] or not row["ts"]:
            continue
        rows.append(row)
    return rows


def rows_to_csv(rows_by_id):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for row in sorted(rows_by_id.values(), key=lambda r: (r.get("ts", ""), r.get("id", ""))):
        w.writerow({c: row.get(c, "") for c in COLUMNS})
    return "\ufeff" + buf.getvalue()          # BOM so Excel shows symbols correctly


def csv_to_rows(text):
    text = (text or "").lstrip("\ufeff")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("id"):
            out[row["id"]] = {c: row.get(c, "") or "" for c in COLUMNS}
    return out


def _num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _derive(rows):
    """Self-healing columns, recomputed from the raw numbers every time:
    * hit_5m/10m/15m  = did price move in the alert direction (price vs spot_at_alert)
    * a missing spot_at_alert is taken from the linked Phase-3 row of the SAME alert
      (recorded within a second of it) and marked spot_src = p3_setup."""
    for r in rows.values():
        if not _num(r.get("spot_at_alert")):
            link = rows.get(r.get("p3_setup_id") or "")
            if link and link is not r and _num(link.get("spot_at_alert")):
                r["spot_at_alert"] = link["spot_at_alert"]
                r["spot_src"] = "p3_setup"
        sgn = {"BULLISH": 1, "BEARISH": -1}.get(r.get("direction"))
        spot = _num(r.get("spot_at_alert"))
        for h in ("5m", "10m", "15m"):
            price = _num(r.get(f"price_{h}"))
            if sgn is not None and spot is not None and price is not None:
                r[f"hit_{h}"] = "True" if (price - spot) * sgn > 0 else "False"
    return rows


def merge_rows(remote_rows, local_rows):
    """Never drops a remote row. Local non-empty values win (they are newer)."""
    out = {k: dict(v) for k, v in remote_rows.items()}
    for r in local_rows:
        cur = out.get(r["id"])
        if cur is None:
            out[r["id"]] = dict(r)
        else:
            for c in COLUMNS:
                if r.get(c) not in ("", None):
                    cur[c] = r[c]
    return _derive(out)


# ------------------------------------------------------------------- GitHub
def _headers(cfg):
    return {"Authorization": f"Bearer {cfg['token']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _url(cfg, path):
    return f"{GH_API}/repos/{cfg['repo']}/contents/{path}"


def _err(resp):
    try:
        msg = (resp.json() or {}).get("message", "")
    except Exception:
        msg = ""
    return f"HTTP {resp.status_code} {msg[:80]}".strip()


def push_day(cfg, date, local_rows, gh):
    """Returns (ok, error_text). Never raises."""
    path = f"alerts/{date}_alerts.csv"
    try:
        cache = gh["cache"].get(date)
        if cache is None:
            params = {"ref": cfg["branch"]} if cfg.get("branch") else None
            r = _http_get(_url(cfg, path), _headers(cfg), params)
            if r.status_code == 200:
                j = r.json()
                text = base64.b64decode(j.get("content", "")).decode("utf-8", errors="replace")
                cache = {"rows": csv_to_rows(text), "sha": j.get("sha")}
            elif r.status_code == 404:
                cache = {"rows": {}, "sha": None}
            else:
                return False, "read failed: " + _err(r)
        merged = merge_rows(cache["rows"], local_rows)
        text = rows_to_csv(merged)
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        if gh["hashes"].get(date) == digest:
            gh["cache"][date] = {"rows": merged, "sha": cache["sha"]}
            return True, None
        payload = {"message": f"nifty log {date} ({len(merged)} rows)",
                   "content": base64.b64encode(text.encode("utf-8")).decode("ascii")}
        if cache["sha"]:
            payload["sha"] = cache["sha"]
        if cfg.get("branch"):
            payload["branch"] = cfg["branch"]
        r = _http_put(_url(cfg, path), _headers(cfg), payload)
        if r.status_code in (200, 201):
            sha = ((r.json() or {}).get("content") or {}).get("sha")
            gh["cache"][date] = {"rows": merged, "sha": sha}
            gh["hashes"][date] = digest
            return True, None
        if r.status_code in (409, 422):
            gh["cache"].pop(date, None)           # stale sha — refetch next time
        return False, "write failed: " + _err(r)
    except Exception as e:                        # network error etc. Only the type is kept.
        return False, f"{type(e).__name__}"


def sync(gh, now, cfg, records_fn, logged_count, background=True, force=False):
    """Push new/changed rows. Cheap no-op unless something changed and 60 s passed."""
    if not cfg or not cfg.get("token") or not cfg.get("repo"):
        gh["configured"] = False
        return
    gh["configured"] = True
    if gh["busy"]:
        return
    if not force and gh["last_push"] is not None and \
            (now - gh["last_push"]).total_seconds() < GH_MIN_INTERVAL_SEC:
        return
    if logged_count == gh["pushed_logged"]:
        return
    records = records_fn()
    rows = records_to_rows(records)
    if not rows:
        return
    by_date = {}
    for r in rows:
        by_date.setdefault(r["ts"][:10], []).append(r)
    gh["last_push"] = now
    gh["busy"] = True

    def work():
        try:
            all_ok, last_err = True, None
            for date, drows in by_date.items():
                ok, err = push_day(cfg, date, drows, gh)
                if not ok:
                    all_ok, last_err = False, err
            if all_ok:
                gh["last_ok"], gh["last_error"] = now, None
                gh["pushes"] += 1
                gh["pushed_logged"] = logged_count
            else:
                gh["last_error"] = last_err
        finally:
            gh["busy"] = False

    if background:
        threading.Thread(target=work, daemon=True).start()
    else:
        work()
