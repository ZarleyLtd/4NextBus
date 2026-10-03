"""Runtime configuration for the Lambda (env vars + SSM for the secret)."""
from __future__ import annotations

import os
from functools import lru_cache


TABLE_NAME = os.environ.get("FOURNEXTBUS_TABLE", "FourNextBus")
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "eu-west-1"
SKILL_ID = os.environ.get("ALEXA_SKILL_ID")  # verified by ask-sdk when set
NTA_KEY_PARAM = os.environ.get("NTA_API_KEY_PARAM", "/4nextbus/nta_api_key")


@lru_cache(maxsize=1)
def nta_api_key() -> str:
    """Prefer an explicit env var (local dev/tests); otherwise read the SSM SecureString once."""
    direct = os.environ.get("NTA_API_KEY", "").strip()
    if direct:
        return direct
    import boto3
    ssm = boto3.client("ssm", region_name=REGION)
    return ssm.get_parameter(Name=NTA_KEY_PARAM, WithDecryption=True)["Parameter"]["Value"].strip()
