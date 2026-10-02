# garmin-wellness

Pulls last night's sleep, HRV, resting HR, body battery, stress and training
readiness from Garmin Connect every morning with GitHub Actions, and commits it
to `data/`. Claude's daily training check-in reads `data/latest.json` and
`data/daily.csv`.

**Keep this repository private.** It holds your health data. The Garmin login
tokens are stored encrypted in `state/tokens.enc`; the key lives only in the
`GARMIN_TOKEN_KEY` repository secret. Your password is never stored.

## One-time setup (on your laptop)

```bash
git clone https://github.com/oyvindar/garmin-wellness.git
cd garmin-wellness
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python setup_token.py
```

1. `setup_token.py` asks for your Garmin email, password and MFA code (if any),
   then prints a key.
2. On GitHub: **Settings → Secrets and variables → Actions → New repository
   secret**. Name: `GARMIN_TOKEN_KEY`, value: the printed key.
3. Commit and push the encrypted tokens:
   ```bash
   git add state/tokens.enc && git commit -m "Add Garmin tokens" && git push
   ```
4. **Actions → Daily Garmin recovery data → Run workflow** to test. After a
   minute, `data/latest.json` should appear.

## When it breaks

`data/status.json` says what went wrong. If login fails (tokens expired or
Garmin changed something), run `python setup_token.py` again, update the
secret, and push the new `state/tokens.enc`. If a newer `garminconnect`
release fixes a Garmin change, bump the version in `requirements.txt`.

## Files

| Path | What |
|---|---|
| `data/latest.json` | Last night's summary |
| `data/daily.csv` | One row per day, the running history |
| `data/YYYY-MM-DD.json` | Daily summary |
| `data/raw/YYYY-MM-DD.json` | Raw Garmin responses, for anything the summary misses |
| `data/status.json` | Whether the last run worked |
