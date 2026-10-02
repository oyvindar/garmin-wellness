"""Daily fetch, run by GitHub Actions.

Decrypts the Garmin tokens, pulls last night's recovery data plus yesterday's
daily summary, writes data/YYYY-MM-DD.json and data/latest.json, appends a row
to data/daily.csv, and re-encrypts the (possibly refreshed) tokens.
"""
import csv
import json
import os
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from garminconnect import Garmin

ROOT = Path(__file__).parent
STATE = ROOT / "state" / "tokens.enc"
DATA = ROOT / "data"
OSLO = ZoneInfo("Europe/Oslo")


def g(d, *path, default=None):
    """Safe nested get: g(obj, 'a', 'b', 0, 'c')."""
    for p in path:
        try:
            d = d[p]
        except (KeyError, IndexError, TypeError):
            return default
        if d is None:
            return default
    return d


def local_clock(ms):
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(OSLO).strftime("%H:%M")


def safe(fn, *args):
    try:
        return fn(*args)
    except Exception as e:  # keep going: one failing endpoint should not lose the rest
        return {"_error": f"{type(e).__name__}: {e}"}


def summarise(today: str, yday: str, raw: dict) -> dict:
    sl, hrv, rd, st, ts = raw["sleep"], raw["hrv"], raw["readiness"], raw["stats_yesterday"], raw["training_status"]
    dto = g(sl, "dailySleepDTO", default={}) or {}
    secs = lambda k: dto.get(k) or 0
    asleep = secs("deepSleepSeconds") + secs("lightSleepSeconds") + secs("remSleepSeconds")
    # Readiness is recalculated during the day (after each workout). Keep the
    # wake-up value as the headline, and the most recent one separately.
    entries = rd if isinstance(rd, list) else ([rd] if isinstance(rd, dict) and "score" in rd else [])
    entries = sorted(entries, key=lambda e: e.get("timestamp") or "")
    wake = next((e for e in entries if e.get("inputContext") == "AFTER_WAKEUP_RESET"), entries[0] if entries else {})
    latest = entries[-1] if entries else {}
    readiness = wake
    vo2 = g(ts, "mostRecentVO2Max", "generic", "vo2MaxPreciseValue") or g(ts, "mostRecentVO2Max", "generic", "vo2MaxValue")
    status_map = g(ts, "mostRecentTrainingStatus", "latestTrainingStatusData", default={}) or {}
    tstatus = next(iter(status_map.values()), {}) if isinstance(status_map, dict) and status_map else {}
    return {
        "date": today,
        "sleep_start": local_clock(dto.get("sleepStartTimestampGMT")),
        "sleep_end": local_clock(dto.get("sleepEndTimestampGMT")),
        "sleep_h": round(asleep / 3600, 2) if asleep else None,
        "deep_h": round(secs("deepSleepSeconds") / 3600, 2) or None,
        "rem_h": round(secs("remSleepSeconds") / 3600, 2) or None,
        "awake_min": round(secs("awakeSleepSeconds") / 60) if dto else None,
        "sleep_score": g(dto, "sleepScores", "overall", "value"),
        "hrv_last_night": g(hrv, "hrvSummary", "lastNightAvg") or g(sl, "avgOvernightHrv"),
        "hrv_weekly_avg": g(hrv, "hrvSummary", "weeklyAvg"),
        "hrv_baseline_low": g(hrv, "hrvSummary", "baseline", "balancedLow"),
        "hrv_baseline_high": g(hrv, "hrvSummary", "baseline", "balancedUpper"),
        "hrv_status": g(hrv, "hrvSummary", "status") or g(sl, "hrvStatus"),
        "resting_hr": g(sl, "restingHeartRate") or g(st, "restingHeartRate"),
        "sleep_respiration": dto.get("averageRespirationValue"),
        "body_battery_change_overnight": g(sl, "bodyBatteryChange"),
        "readiness_score": readiness.get("score"),
        "readiness_level": readiness.get("level"),
        "recovery_time_h": round(readiness["recoveryTime"] / 60, 1) if readiness.get("recoveryTime") is not None else None,
        "readiness_now": latest.get("score"),
        "readiness_now_context": latest.get("inputContext"),
        "training_status": tstatus.get("trainingStatusFeedbackPhrase") or tstatus.get("trainingStatus"),
        "acute_load": g(tstatus, "acuteTrainingLoadDTO", "dailyTrainingLoadAcute"),
        "chronic_load": g(tstatus, "acuteTrainingLoadDTO", "dailyTrainingLoadChronic"),
        "vo2max": vo2,
        "yesterday": yday,
        "yesterday_steps": st.get("totalSteps") if isinstance(st, dict) else None,
        "yesterday_avg_stress": st.get("averageStressLevel") if isinstance(st, dict) else None,
        "yesterday_body_battery_high": st.get("bodyBatteryHighestValue") if isinstance(st, dict) else None,
        "yesterday_body_battery_low": st.get("bodyBatteryLowestValue") if isinstance(st, dict) else None,
    }


def write_status(ok: bool, **extra) -> None:
    print("STATUS:", ok, extra)
    DATA.mkdir(exist_ok=True)
    (DATA / "status.json").write_text(json.dumps(
        {"ok": ok, "ran_at": datetime.now(OSLO).isoformat(timespec="minutes"), **extra}, indent=2))


def main() -> int:
    key = os.environ.get("GARMIN_TOKEN_KEY")
    if not key or not STATE.exists():
        write_status(False, error="Missing GARMIN_TOKEN_KEY secret or state/tokens.enc. Run setup_token.py.")
        return 1
    f = Fernet(key.encode())
    try:
        api = Garmin()
        api.login(f.decrypt(STATE.read_bytes()).decode())
    except Exception as e:
        write_status(False, error=f"Login failed ({type(e).__name__}). Tokens probably expired: run setup_token.py again.")
        traceback.print_exc()
        return 1

    today = datetime.now(OSLO).date()
    yday = today - timedelta(days=1)
    t, y = today.isoformat(), yday.isoformat()
    raw = {
        "sleep": safe(api.get_sleep_data, t),
        "hrv": safe(api.get_hrv_data, t),
        "readiness": safe(api.get_training_readiness, t),
        "training_status": safe(api.get_training_status, t),
        "stats_yesterday": safe(api.get_stats, y),
    }
    summary = summarise(t, y, raw)

    DATA.mkdir(exist_ok=True)
    (DATA / "raw").mkdir(exist_ok=True)
    (DATA / "raw" / f"{t}.json").write_text(json.dumps(raw, indent=1, default=str))
    (DATA / f"{t}.json").write_text(json.dumps(summary, indent=2))
    (DATA / "latest.json").write_text(json.dumps(summary, indent=2))

    csv_path = DATA / "daily.csv"
    rows = []
    if csv_path.exists():
        with csv_path.open() as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("date") != t]
    rows.append({k: ("" if v is None else v) for k, v in summary.items()})
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary.keys()))
        w.writeheader()
        w.writerows(rows)

    # Save refreshed tokens so the login keeps working without a new setup.
    STATE.write_bytes(f.encrypt(api.client.dumps().encode()))
    errors = [k for k, v in raw.items() if isinstance(v, dict) and "_error" in v]
    write_status(True, date=t, endpoint_errors=errors)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
