#!/usr/bin/env python3
"""
Leaderboard collector.

Reads pending score submissions from an ntfy.sh topic and folds them into
data/leaderboard.json. ntfy only retains messages ~12h, so this is meant to
run on a schedule; the JSON file on GitHub Pages is the durable record.

Usage:  python collect.py [--dry-run]
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
LB_PATH = os.path.join(HERE, "data", "leaderboard.json")
TOPIC = "wb-intg-lb-a5fae5bcd226"
MAX_ENTRIES = 500

FIELDS = {
    "player_name": str,
    "status": str,
    "total_score": int,
    "base_score": int,
    "health_score": int,
    "converted_count": int,
    "total_rounds": int,
    "resources_left": int,
    "final_cred": int,
    "final_pressure": int,
    "aggressive_index": int,
    "conservative_index": int,
}


def clamp(v, lo, hi, default=0):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def clean_name(v):
    s = str(v or "").strip()
    s = "".join(ch for ch in s if ch.isprintable())
    return s[:20] or "Anonymous"


def norm(rec):
    """Validate + normalise one submission. Returns None if unusable."""
    if not isinstance(rec, dict):
        return None
    # accept either a bare record or {"type":"score","payload":{...}}
    if "payload" in rec and isinstance(rec["payload"], dict):
        rec = rec["payload"]
    if "total_score" not in rec and "totalScore" not in rec:
        return None

    out = {
        "player_name": clean_name(rec.get("player_name") or rec.get("playerName")),
        "status": "win" if str(rec.get("status", "")).lower() == "win" else "fail",
        "total_score": clamp(rec.get("total_score", rec.get("totalScore")), 0, 100),
        "base_score": clamp(rec.get("base_score", rec.get("baseScore")), 0, 100),
        "health_score": clamp(rec.get("health_score", rec.get("healthScore")), 0, 100),
        "converted_count": clamp(rec.get("converted_count", rec.get("convertedCount")), 0, 99),
        "total_rounds": clamp(rec.get("total_rounds", rec.get("totalRounds")), 1, 999, 1),
        "resources_left": clamp(rec.get("resources_left", rec.get("resourcesLeft")), 0, 99999),
        "final_cred": clamp(rec.get("final_cred", rec.get("finalCred")), 0, 9999),
        "final_pressure": clamp(rec.get("final_pressure", rec.get("finalPressure")), 0, 9999),
        "aggressive_index": clamp(rec.get("aggressive_index", rec.get("aggressiveIndex")), 0, 9999),
        "conservative_index": clamp(rec.get("conservative_index", rec.get("conservativeIndex")), 0, 9999),
    }
    ts = rec.get("ts") or rec.get("timestamp") or rec.get("created_at")
    if isinstance(ts, (int, float)) and ts > 1e11:      # ms
        ts = ts / 1000.0
    if not isinstance(ts, (int, float)) or ts <= 0:
        ts = time.time()
    out["ts"] = int(ts)
    return out


def dedupe_key(r):
    """One player can legitimately play many times, but the same submission
    must not be counted twice if ntfy is polled repeatedly."""
    return (r["player_name"], r["ts"], r["total_score"])


def fetch_pending():
    url = "https://ntfy.sh/%s/json?poll=1&since=all" % TOPIC
    req = urllib.request.Request(url, headers={"User-Agent": "wb-lb-collector/1"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        print("ntfy HTTP %s: %s" % (e.code, e.read().decode()[:200]))
        return []
    except Exception as e:
        print("ntfy unreachable: %s" % e)
        return []

    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("event") != "message":
            continue
        msg = ev.get("message") or ""
        try:
            payload = json.loads(msg)
        except ValueError:
            continue                     # not ours (or malformed) - skip
        r = norm(payload)
        if r:
            # keep ntfy's own publish time so first-seen ordering is stable
            r["ts"] = int(ev.get("time") or r["ts"])
            out.append(r)
    return out


def main():
    dry = "--dry-run" in sys.argv
    with open(LB_PATH, "r", encoding="utf-8") as f:
        doc = json.load(f)

    existing = doc.get("scores", [])
    seen = {dedupe_key(r) for r in existing
            if isinstance(r, dict) and "ts" in r and "total_score" in r}

    incoming = fetch_pending()
    added = []
    for r in incoming:
        k = dedupe_key(r)
        if k in seen:
            continue
        seen.add(k)
        added.append(r)

    print("existing=%d  incoming=%d  new=%d" % (len(existing), len(incoming), len(added)))
    if not added and not dry:
        print("nothing to do")
        return 0

    merged = existing + added
    merged.sort(key=lambda r: (-r.get("total_score", 0), r.get("ts", 0)))
    merged = merged[:MAX_ENTRIES]

    if dry:
        for r in added[:20]:
            print("  + %s %s %s" % (r["player_name"], r["total_score"], r["status"]))
        return 0

    doc["scores"] = merged
    doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp = LB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LB_PATH)
    print("wrote %d entries to %s" % (len(merged), LB_PATH))
    return 0


if __name__ == "__main__":
    sys.exit(main())
