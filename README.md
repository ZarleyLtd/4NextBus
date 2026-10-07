# 4NextBus

Alexa skill that tells you when the next Dublin buses are due at a stop, rebuilt on the
NTA GTFS-Realtime API. Invocation name: **four next bus**.

- "Alexa, ask four next bus from stop 184"
- "Alexa, ask four next bus to set my favourite stop to 184"
- "Alexa, ask four next bus for my favourite stop"
- "Alexa, ask four next bus" (uses your favourite)

The full intent and utterance list is in [Voice model](#voice-model). Copy that section when
building a sibling skill (for example a Luas/tram skill): same three custom intents, one
`AMAZON.NUMBER` slot, and the same Lambda handler shape.

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

## Voice model

Canonical files:

- Interaction model: [`skill-package/interactionModels/custom/en-GB.json`](skill-package/interactionModels/custom/en-GB.json)
- Store listing, example phrases, testing instructions: [`skill-package/skill.json`](skill-package/skill.json)
- Request handlers: [`src/skill/app.py`](src/skill/app.py)

Paste the JSON into the Alexa console **Build → Interaction Model → JSON Editor**, then Save
and Build. Extra English locales on a *published* skill cannot be dropped; this live skill
keeps `en-US` / `en-AU` / `en-CA` / `en-IN` as copies of the same model. A new unpublished
skill can start with `en-GB` only.

### Invocation vs display name

| What users see / say | Value |
| --- | --- |
| Skill name (store and console) | `4NextBus` |
| Invocation name (spoken) | `four next bus` |

"Alexa" and "ask" are launch words, not part of the invocation. Sample utterances in the
interaction model are **only the tail after the invocation**. Do not put `Alexa, ask four
next bus` into `samples`.

Check the customer store (`amazon.co.uk` for IE/GB) that no live skill already uses the
invocation you want. Invocation names are not globally unique, but a hidden or live skill
with the same phrase can still intercept.

### What the user says (full phrases)

These are the phrases to test on a phone or in the console Test tab.

| User says | Request | Slot |
| --- | --- | --- |
| Alexa, open four next bus | `LaunchRequest` | — |
| Alexa, ask four next bus | `LaunchRequest` | — |
| Alexa, ask four next bus from stop 184 | `NextBusIntent` | `stopNumber` = 184 |
| Alexa, ask four next bus for the next bus | `NextBusIntent` | none (uses favourite) |
| Alexa, ask four next bus to set my favourite stop to 184 | `SetFavouriteStopIntent` | `stopNumber` = 184 |
| Alexa, ask four next bus for my favourite stop | `GetFavouriteStopIntent` | — |
| Alexa, ask four next bus for help | `AMAZON.HelpIntent` | — |
| Alexa, ask four next bus to stop | `AMAZON.StopIntent` | — |

Store listing `examplePhrases` (Amazon allows three):

1. `Alexa, ask four next bus from stop 184`
2. `Alexa, ask four next bus to set my favourite stop to 184`
3. `Alexa, ask four next bus for the next bus`

### Custom intents

One optional slot everywhere a pole number is needed: `stopNumber`, type `AMAZON.NUMBER`.
Numbers are the printed `stop_code` on the pole (for example `184`), not the GTFS `stop_id`.

Dialog is `SKILL_RESPONSE` (the Lambda elicits, Amazon does not auto-delegate). If
`SetFavouriteStopIntent` or `NextBusIntent` (with no favourite) is missing `stopNumber`, the
handler returns an `ElicitSlotDirective` for `stopNumber`. Prompts: "Which stop number?" /
"What's the number on the bus stop pole?"

#### `NextBusIntent`

Times at a given stop, or at the saved favourite if no number is spoken.

Samples with a stop number:

- `from stop {stopNumber}`
- `from stop number {stopNumber}`
- `for stop {stopNumber}`
- `for stop number {stopNumber}`
- `stop {stopNumber}`
- `stop number {stopNumber}`
- `buses from stop {stopNumber}`
- `buses at stop {stopNumber}`
- `the next bus from stop {stopNumber}`
- `the next bus at stop {stopNumber}`
- `when is the next bus from stop {stopNumber}`
- `when is the next bus at stop {stopNumber}`
- `what's the next bus from stop {stopNumber}`
- `what time is the next bus from stop {stopNumber}`

Samples that use the favourite (no slot):

- `next bus`
- `next buses`
- `the next bus`
- `for the next bus`
- `for the next buses`
- `when is the next bus`
- `when is my next bus`
- `what's the next bus`
- `what time is the next bus`
- `from my favourite stop`
- `from my stop`
- `for my stop`
- `buses from my favourite stop`
- `the next bus from my favourite stop`

Handler: if `stopNumber` is present, resolve it and speak times; if not, use the favourite;
if there is no favourite, elicit the slot.

#### `SetFavouriteStopIntent`

Saves one favourite stop per Alexa user id (`USER#…` / `PROFILE` in DynamoDB).

- `to set my favourite stop to {stopNumber}`
- `set my favourite stop to {stopNumber}`
- `set my favourite stop to stop {stopNumber}`
- `set favourite stop {stopNumber}`
- `set my favourite stop` (elicits the number)
- `to set my favourite stop`
- `change my favourite stop to {stopNumber}`
- `to change my favourite stop to {stopNumber}`
- `make {stopNumber} my favourite stop`
- `make stop {stopNumber} my favourite`
- `remember stop {stopNumber}`
- `to remember stop {stopNumber}`
- `save stop {stopNumber}`
- `to save stop {stopNumber} as my favourite`
- `my stop is {stopNumber}`
- `to set my favorite stop to {stopNumber}` (US spelling, for copied locales)
- `set my favorite stop to {stopNumber}`

#### `GetFavouriteStopIntent`

Read-back only. No slots.

- `for my favourite stop`
- `what is my favourite stop`
- `what's my favourite stop`
- `what is my favourite stop number`
- `which stop is my favourite`
- `to remind me of my favourite stop`
- `what stop is saved`
- `for my favorite stop`
- `what is my favorite stop`

### Built-in intents and other requests

| Name | Role |
| --- | --- |
| `LaunchRequest` | Open/ask with no intent: speak times for the favourite, or welcome + ask for a stop |
| `AMAZON.HelpIntent` | How to ask for a stop or save a favourite |
| `AMAZON.StopIntent` / `AMAZON.CancelIntent` | "Goodbye." and end session |
| `AMAZON.FallbackIntent` | Apology + help, keep session open |
| `AMAZON.NavigateHomeIntent` | Declared; no custom samples |
| `SessionEndedRequest` | No speech |

### Spoken result (after NLU)

Handled in `src/common/predictions.py` / `src/common/speech.py`, not in the interaction
model: every bus due in the next 10 minutes, at least 3, at most about 8; "due" under one
minute; "scheduled" when there is no realtime update.

### Copying this for a sibling skill

Keep the same intent names and slot name so `src/skill/app.py` can stay almost unchanged.
Then edit:

1. `invocationName` (must be spoken English words, not `4NextLuas`).
2. Sample wording (`bus` → `tram` / `Luas`, stop-pole copy if the numbered stops differ).
3. `skill.json` name, summary, description, example phrases, keywords, category, privacy URL.
4. Help / welcome / error strings in `src/skill/app.py`.
5. Ingest filter if the mode is not GTFS `route_type` 3 (this skill is bus only).

Wire the new skill ID as `ALEXA_SKILL_ID` (a second ID is optional in `template.yaml` as
`SecondSkillId`). Do not reuse this live skill's ID `amzn1.ask.skill.f324eb14-…`.

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
   `AWS_SECRET_ACCESS_KEY`. The workflow in `.github/workflows/ingest.yml` is scheduled at
   00:10 UTC (after TFI's usual evening zip). GitHub public-repo crons often start hours late.

Later code changes: `python tools/deploy.py code`. Template changes: `python tools/deploy.py stack ...`.

## Data sources

- Realtime: `https://api.nationaltransport.ie/gtfsr/v2/TripUpdates` (header `x-api-key`), max 1 call / 60 s.
- Static timetable: `https://www.transportforireland.ie/transitData/Data/GTFS_Realtime.zip` (updated daily).
- Users say the pole number (`stop_code`); the feed uses `stop_id` (e.g. `8220DB000184`).

## Free tier

Everything runs inside AWS Always Free allowances (Lambda, one provisioned DynamoDB table,
CloudWatch Logs, SSM Parameter Store) plus GitHub Actions for the daily timetable build.
No S3, no Secrets Manager. See the plan for headroom figures.
