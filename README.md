# 4NextBus

Alexa skill that tells you when the next Dublin buses are due at a stop, rebuilt on the
NTA GTFS-Realtime API. Invocation name: **four next bus**.

- "Alexa, ask four next bus from stop 184"
- "Alexa, ask four next bus to set my favourite stop to 184"
- "Alexa, ask four next bus for my favourite stop"
- "Alexa, ask four next bus" (uses your favourite)

## Layout

```
src/common/        shared logic: GTFS time handling, predictions, realtime fetch, speech, DynamoDB store
src/skill/         Lambda handler (ask-sdk-core)
ingest/            daily timetable build (DuckDB over the TFI GTFS zip -> DynamoDB)
tools/             local proof-of-concept and helper scripts
skill-package/     Alexa skill manifest and en-GB interaction model
tests/             pytest
template.yaml      CloudFormation: DynamoDB table, Lambda, role, SSM parameter
```

## Local setup (Windows / PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
copy .env.example .env   # then fill in NTA_API_KEY
.\.venv\Scripts\python tools\poc_next_bus.py 184
```

If `pip` fails with `CERTIFICATE_VERIFY_FAILED`, an antivirus or proxy is intercepting TLS.
Bootstrap once with `--trusted-host pypi.org --trusted-host files.pythonhosted.org --upgrade pip truststore`;
newer pip then uses the Windows certificate store automatically. The local tools call
`truststore.inject_into_ssl()` for the same reason. Never use `verify=False`.

## Data sources

- Realtime: `https://api.nationaltransport.ie/gtfsr/v2/TripUpdates` (header `x-api-key`), max 1 call / 60 s.
- Static timetable: `https://www.transportforireland.ie/transitData/Data/GTFS_Realtime.zip` (updated daily).
- Users say the pole number (`stop_code`); the feed uses `stop_id` (e.g. `8220DB000184`).

## Free tier

Everything runs inside AWS Always Free allowances (Lambda, one provisioned DynamoDB table,
CloudWatch Logs, SSM Parameter Store) plus GitHub Actions for the daily timetable build.
No S3, no Secrets Manager. See the plan for headroom figures.
