"""Deploy 4NextBus to AWS using boto3 only (no AWS CLI, no SAM, no S3 bucket).

  python tools/deploy.py stack --skill-id amzn1.ask.skill.xxx --email you@example.com
  python tools/deploy.py key            # store NTA_API_KEY from .env as an SSM SecureString
  python tools/deploy.py code           # build the Lambda zip and upload it directly
  python tools/deploy.py ingest-key     # create an access key for the GitHub Actions user (printed once)
  python tools/deploy.py all --skill-id ... --email ...
  python tools/deploy.py stack --dev --skill-id amzn1.ask.skill.devcopy
  python tools/deploy.py code --dev
  python tools/deploy.py test --dev --intent NextLuasIntent --station Dundrum --direction southbound

--dev updates FourNextBus-Dev-Skill only (shared FourNextBus table). Live FourNextBus-Skill stays unchanged.

Credentials: standard boto3 resolution (AWS_PROFILE / ~/.aws/credentials / env vars).
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
REGION = os.environ.get("AWS_REGION", "eu-west-1")
STACK = os.environ.get("FOURNEXTBUS_STACK", "FourNextBus")
TABLE = os.environ.get("FOURNEXTBUS_TABLE", "FourNextBus")
FUNCTION = os.environ.get("FOURNEXTBUS_FUNCTION", "FourNextBus-Skill")
PARAM = os.environ.get("NTA_API_KEY_PARAM", "/4nextbus/nta_api_key")
LAMBDA_PY = "3.13"


def session():
    return boto3.session.Session(region_name=REGION)


# ---- stack -------------------------------------------------------------------------------

def deploy_stack(skill_id: str, email: str, reserved: str) -> None:
    cfn = session().client("cloudformation")
    template = (ROOT / "template.yaml").read_text(encoding="utf-8")
    ids = [s.strip() for s in skill_id.split(",") if s.strip()]
    if not 1 <= len(ids) <= 2:
        sys.exit("--skill-id takes one or two comma-separated skill IDs")
    params = [
        {"ParameterKey": "SkillId", "ParameterValue": ids[0]},
        {"ParameterKey": "SecondSkillId", "ParameterValue": ids[1] if len(ids) > 1 else ""},
        {"ParameterKey": "AlertEmail", "ParameterValue": email},
        {"ParameterKey": "TableName", "ParameterValue": TABLE},
        {"ParameterKey": "FunctionName", "ParameterValue": FUNCTION},
        {"ParameterKey": "NtaKeyParameterName", "ParameterValue": PARAM},
        {"ParameterKey": "ReservedConcurrency", "ParameterValue": reserved},
    ]
    kwargs = dict(StackName=STACK, TemplateBody=template, Parameters=params,
                  Capabilities=["CAPABILITY_NAMED_IAM"])
    try:
        cfn.describe_stacks(StackName=STACK)
        exists = True
    except ClientError:
        exists = False
    try:
        if exists:
            print(f"updating stack {STACK} ...")
            cfn.update_stack(**kwargs)
            waiter = cfn.get_waiter("stack_update_complete")
        else:
            print(f"creating stack {STACK} ...")
            cfn.create_stack(**kwargs, OnFailure="DELETE")
            waiter = cfn.get_waiter("stack_create_complete")
    except ClientError as exc:
        if "No updates are to be performed" in str(exc):
            print("stack already up to date")
            return
        raise
    waiter.wait(StackName=STACK, WaiterConfig={"Delay": 10, "MaxAttempts": 90})
    outputs = cfn.describe_stacks(StackName=STACK)["Stacks"][0].get("Outputs", [])
    print("stack ready:")
    for o in outputs:
        print(f"  {o['OutputKey']}: {o['OutputValue']}")


# ---- NTA key -----------------------------------------------------------------------------

def put_key() -> None:
    key = os.environ.get("NTA_API_KEY", "").strip()
    if not key:
        key = input("NTA API key: ").strip()
    ssm = session().client("ssm")
    ssm.put_parameter(Name=PARAM, Value=key, Type="SecureString", Overwrite=True,
                      Description="4NextBus NTA GTFS-R subscription key")
    print(f"stored {PARAM} ({key[:4]}...{key[-4:]})")


# ---- code --------------------------------------------------------------------------------

def build_zip() -> bytes:
    build = ROOT / "build" / "lambda"
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)
    print("installing runtime dependencies for Lambda (manylinux, python", LAMBDA_PY, ") ...")
    cmd = [sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt"),
           "--target", str(build), "--platform", "manylinux2014_x86_64", "--implementation", "cp",
           "--python-version", LAMBDA_PY, "--only-binary=:all:", "--upgrade"]
    subprocess.run(cmd, check=True)
    # boto3/botocore come with the Lambda runtime; drop them if a dependency pulled them in.
    for junk in ["boto3", "botocore", "s3transfer", "bin", "__pycache__"]:
        p = build / junk
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    for dist in build.glob("*.dist-info"):
        if dist.name.split("-")[0] in ("boto3", "botocore", "s3transfer"):
            shutil.rmtree(dist, ignore_errors=True)
    shutil.copytree(ROOT / "src", build / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(build.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                info = zipfile.ZipInfo(path.relative_to(build).as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
                info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, path.read_bytes())
    data = buf.getvalue()
    (ROOT / "build" / "lambda.zip").write_bytes(data)
    print(f"built build/lambda.zip: {len(data)/1e6:.1f} MB")
    return data


def ensure_skill_ddb_delete() -> None:
    """Forget-favourite uses DeleteItem; the original skill role only had Get/Put/Update."""
    import json
    iam = session().client("iam")
    lam = session().client("lambda")
    live_name = os.environ.get("FOURNEXTBUS_FUNCTION", "FourNextBus-Skill")
    cfg = lam.get_function_configuration(FunctionName=live_name)
    role_name = cfg["Role"].rsplit("/", 1)[-1]
    doc = iam.get_role_policy(RoleName=role_name, PolicyName="skill")["PolicyDocument"]
    changed = False
    for stmt in doc.get("Statement") or []:
        actions = stmt.get("Action")
        if isinstance(actions, str):
            actions = [actions]
        if not isinstance(actions, list):
            continue
        if "dynamodb:PutItem" in actions and "dynamodb:DeleteItem" not in actions:
            stmt["Action"] = list(actions) + ["dynamodb:DeleteItem"]
            changed = True
    if not changed:
        print(f"IAM {role_name}: DeleteItem already allowed")
        return
    iam.put_role_policy(RoleName=role_name, PolicyName="skill", PolicyDocument=json.dumps(doc))
    print(f"IAM {role_name}: added dynamodb:DeleteItem")


def deploy_code() -> None:
    ensure_skill_ddb_delete()
    data = build_zip()
    lam = session().client("lambda")
    print(f"uploading to {FUNCTION} ...")
    lam.update_function_code(FunctionName=FUNCTION, ZipFile=data, Publish=False)
    lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
    cfg = lam.get_function_configuration(FunctionName=FUNCTION)
    print(f"deployed: {cfg['FunctionArn']} runtime={cfg['Runtime']} size={cfg['CodeSize']/1e6:.1f} MB "
          f"state={cfg['State']} lastUpdate={cfg['LastUpdateStatus']}")


# ---- ingest user key ---------------------------------------------------------------------

def create_ingest_key() -> None:
    iam = session().client("iam")
    user = f"{TABLE}-ingest"
    existing = iam.list_access_keys(UserName=user)["AccessKeyMetadata"]
    if len(existing) >= 2:
        sys.exit(f"{user} already has 2 access keys; delete one in the IAM console first.")
    key = iam.create_access_key(UserName=user)["AccessKey"]
    print("Add these to the GitHub repository secrets (shown once):")
    print(f"  AWS_ACCESS_KEY_ID     = {key['AccessKeyId']}")
    print(f"  AWS_SECRET_ACCESS_KEY = {key['SecretAccessKey']}")


# ---- smoke test --------------------------------------------------------------------------

def ensure_dev_function(skill_id: str) -> None:
    """Clone the live Lambda as FourNextBus-Dev-Skill, same role and table, new Alexa skill ID."""
    import json
    lam = session().client("lambda")
    logs = session().client("logs")
    live_name = os.environ.get("FOURNEXTBUS_FUNCTION", "FourNextBus-Skill")
    live = lam.get_function_configuration(FunctionName=live_name)
    log_group = f"/aws/lambda/{FUNCTION}"
    try:
        logs.create_log_group(logGroupName=log_group)
        logs.put_retention_policy(logGroupName=log_group, retentionInDays=14)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise
    env = dict((live.get("Environment") or {}).get("Variables") or {})
    env["FOURNEXTBUS_TABLE"] = TABLE
    env["ALEXA_SKILL_ID"] = skill_id
    try:
        lam.get_function(FunctionName=FUNCTION)
        print(f"{FUNCTION} already exists; updating configuration ...")
        lam.update_function_configuration(
            FunctionName=FUNCTION,
            Role=live["Role"],
            Runtime=live["Runtime"],
            Handler=live["Handler"],
            Timeout=live["Timeout"],
            MemorySize=live["MemorySize"],
            Environment={"Variables": env},
        )
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        print(f"creating {FUNCTION} ...")
        zip_bytes = build_zip()
        lam.create_function(
            FunctionName=FUNCTION,
            Role=live["Role"],
            Runtime=live["Runtime"],
            Handler=live["Handler"],
            Timeout=live["Timeout"],
            MemorySize=live["MemorySize"],
            Architectures=live.get("Architectures") or ["x86_64"],
            Environment={"Variables": env},
            Code={"ZipFile": zip_bytes},
            Description="4NextBus development skill (live FourNextBus-Skill is unchanged)",
        )
        lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION)
    stmt_id = "AlexaDevSkill"
    try:
        lam.remove_permission(FunctionName=FUNCTION, StatementId=stmt_id)
    except ClientError:
        pass
    lam.add_permission(
        FunctionName=FUNCTION,
        StatementId=stmt_id,
        Action="lambda:InvokeFunction",
        Principal="alexa-appkit.amazon.com",
        EventSourceToken=skill_id,
    )
    cfg = lam.get_function_configuration(FunctionName=FUNCTION)
    print(f"dev function ready: {cfg['FunctionArn']}")
    print("Paste that ARN as the development skill endpoint. Leave the live skill on FourNextBus-Skill.")


def invoke_test(stop_code: str, intent_name: str, station: str, direction: str) -> None:
    import json
    lam = session().client("lambda")
    app_id = os.environ.get("ALEXA_SKILL_ID", "test").split(",")[0].strip()
    slots = {}
    if intent_name == "NextBusIntent":
        slots = {"stopNumber": {"name": "stopNumber", "value": stop_code}}
    else:
        prefix = "luas"
        if "Dart" in intent_name:
            prefix = "dart"
        elif "LocalTrain" in intent_name:
            prefix = "train"
        station_slot, direction_slot = f"{prefix}Station", f"{prefix}Direction"
        if station:
            slots[station_slot] = {"name": station_slot, "value": station}
        if direction:
            slots[direction_slot] = {"name": direction_slot, "value": direction}
    event = {
        "version": "1.0",
        "session": {"new": True, "sessionId": "s", "application": {"applicationId": app_id},
                    "user": {"userId": "amzn1.ask.account.DEPLOYTEST"}},
        "context": {"System": {"application": {"applicationId": app_id},
                               "user": {"userId": "amzn1.ask.account.DEPLOYTEST"},
                               "device": {"deviceId": "d", "supportedInterfaces": {}}}},
        "request": {"type": "IntentRequest", "requestId": "r", "locale": "en-GB",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "intent": {"name": intent_name, "confirmationStatus": "NONE", "slots": slots}},
    }
    t0 = time.perf_counter()
    resp = lam.invoke(FunctionName=FUNCTION, Payload=json.dumps(event).encode())
    body = json.loads(resp["Payload"].read())
    print(f"{time.perf_counter()-t0:.2f}s ->", json.dumps(body.get("response", body), indent=2)[:1500])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["stack", "key", "code", "ingest-key", "test", "all"])
    ap.add_argument("--skill-id", default=os.environ.get("ALEXA_SKILL_ID"))
    ap.add_argument("--email", default=os.environ.get("ALERT_EMAIL"))
    ap.add_argument("--reserved-concurrency", default="1", help='"none" if your account quota is too low')
    ap.add_argument("--stop", default="184", help="stop code for the test invocation")
    ap.add_argument("--dev", action="store_true",
                    help="target FourNextBus-Dev-Skill (shared table; live Lambda unchanged)")
    ap.add_argument("--intent", default="NextBusIntent", help="intent name for test")
    ap.add_argument("--station", default="", help="station slot for named-mode test")
    ap.add_argument("--direction", default="", help="direction slot for named-mode test")
    args = ap.parse_args()

    global STACK, FUNCTION
    if args.dev:
        STACK = os.environ.get("FOURNEXTBUS_DEV_STACK", "FourNextBus-Dev")
        FUNCTION = os.environ.get("FOURNEXTBUS_DEV_FUNCTION", "FourNextBus-Dev-Skill")
        print(f"dev target: function={FUNCTION} table={TABLE}")

    if args.action in ("stack", "all"):
        if args.dev:
            if not args.skill_id:
                sys.exit("--skill-id is required for the development Lambda")
            ensure_dev_function(args.skill_id.split(",")[0].strip())
        else:
            if not args.skill_id or not args.email:
                sys.exit("--skill-id and --email are required for the stack (or set ALEXA_SKILL_ID / ALERT_EMAIL in .env)")
            deploy_stack(args.skill_id, args.email, args.reserved_concurrency)
    if args.action in ("key", "all") and not args.dev:
        put_key()
    if args.action in ("code", "all"):
        deploy_code()
    if args.action == "ingest-key":
        create_ingest_key()
    if args.action == "test":
        invoke_test(args.stop, args.intent, args.station, args.direction)


if __name__ == "__main__":
    main()
