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

## Tests

```powershell
.\.venv\Scripts\python -m pytest -q
```

## Deploying (first time)

Everything is driven by `tools/deploy.py` (boto3 only; no AWS CLI or SAM needed).

1. AWS credentials on this PC. In the AWS console create an IAM user with
   `AdministratorAccess` (or at least CloudFormation, IAM, Lambda, DynamoDB, SSM, Logs, Budgets),
   create an access key, and save it to `%USERPROFILE%\.aws\credentials`:

   ```ini
   [default]
   aws_access_key_id = AKIA...
   aws_secret_access_key = ...
   ```

2. Put `ALEXA_SKILL_ID` (from the Alexa developer console, skill list -> "Copy Skill ID"; up to
   two IDs comma-separated if you have a live skill and a development copy),
   `ALERT_EMAIL` and a fresh `NTA_API_KEY` in `.env`.
3. `python tools/deploy.py all` creates the stack (table, Lambda, role, budget, ingest IAM user),
   stores the NTA key in SSM, builds `build/lambda.zip` and uploads it. It prints the Lambda ARN.
4. First timetable load from this PC (about 50 minutes, paced under 25 WCU/s):
   `python -m ingest.build_timetable`
5. In the Alexa developer console: Build -> JSON Editor -> paste
   `skill-package/interactionModels/custom/en-GB.json` -> Save and Build Model.
   Endpoint -> AWS Lambda ARN -> paste the ARN from step 3 -> Save.
6. `python tools/deploy.py test --stop 184` invokes the Lambda directly; then use the
   console Test tab or an Echo: "Alexa, ask four next bus from stop 184".
7. Daily refresh via GitHub Actions: `python tools/deploy.py ingest-key` prints an access key for
   the least-privilege ingest user; add it as repository secrets `AWS_ACCESS_KEY_ID` /
   `AWS_SECRET_ACCESS_KEY`. The workflow in `.github/workflows/ingest.yml` runs at 03:40 UTC.

Later code changes: `python tools/deploy.py code`. Template changes: `python tools/deploy.py stack ...`.

## Data sources

- Realtime: `https://api.nationaltransport.ie/gtfsr/v2/TripUpdates` (header `x-api-key`), max 1 call / 60 s.
- Static timetable: `https://www.transportforireland.ie/transitData/Data/GTFS_Realtime.zip` (updated daily).
- Users say the pole number (`stop_code`); the feed uses `stop_id` (e.g. `8220DB000184`).

## Free tier

Everything runs inside AWS Always Free allowances (Lambda, one provisioned DynamoDB table,
CloudWatch Logs, SSM Parameter Store) plus GitHub Actions for the daily timetable build.
No S3, no Secrets Manager. See the plan for headroom figures.
