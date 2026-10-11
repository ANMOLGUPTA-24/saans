"""The AWS layer.

Saans runs on the Build It path: AWS open-source tooling on a laptop, no
AWS account and no card. LocalStack stands in for the managed services, and
the same boto3 calls work unchanged against real AWS - set SAANS_AWS=real
and the endpoint override drops away.

Four services, each doing a job the project actually needs:

  DynamoDB    the decision ledger. Every morning's call, its evidence and
              the clauses that produced it, keyed by school and date, so a
              parent can ask "why was my daughter kept inside on the 6th"
              a month later and get the same answer the principal got.
  S3          the notice that went home, stored as sent.
  EventBridge the 05:45 IST rule. The decision has to exist before the
              principal needs it, not when someone remembers to click.
  SES         delivery to the principal and to the register's parents.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError

REGION = os.environ.get("AWS_REGION", "ap-south-1")
ENDPOINT = os.environ.get("SAANS_ENDPOINT", "http://localhost:4566")
USE_REAL_AWS = os.environ.get("SAANS_AWS", "local").lower() == "real"

TABLE = "saans-decision-ledger"
BUCKET = "saans-notices"
RULE = "saans-morning-protocol"
SENDER = "protocol@saans.school"

# 05:45 IST, every day. EventBridge cron is UTC, so 00:15 UTC.
MORNING_CRON = "cron(15 0 * * ? *)"

_BOTO = Config(retries={"max_attempts": 2}, connect_timeout=3, read_timeout=8)


def _client(service: str):
    kwargs: dict[str, Any] = {"region_name": REGION, "config": _BOTO}
    if not USE_REAL_AWS:
        kwargs["endpoint_url"] = ENDPOINT
        kwargs["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID", "test")
        kwargs["aws_secret_access_key"] = os.environ.get(
            "AWS_SECRET_ACCESS_KEY", "test"
        )
    return boto3.client(service, **kwargs)


@dataclass
class CloudStatus:
    """Whether each service is actually reachable, for the dashboard.

    Saans degrades honestly: if AWS is not up it says so on the page and
    keeps deciding, rather than pretending the ledger was written.
    """

    mode: str
    dynamodb: bool = False
    s3: bool = False
    eventbridge: bool = False
    ses: bool = False
    detail: dict[str, str] | None = None

    @property
    def any_up(self) -> bool:
        return any([self.dynamodb, self.s3, self.eventbridge, self.ses])

    @property
    def all_up(self) -> bool:
        return all([self.dynamodb, self.s3, self.eventbridge, self.ses])


def _floats_to_decimal(obj: Any) -> Any:
    """DynamoDB stores numbers exactly, so floats go in as Decimal."""
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4)))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(v) for v in obj]
    return obj


def _decimals_to_float(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        f = float(obj)
        return int(f) if f.is_integer() else f
    if isinstance(obj, dict):
        return {k: _decimals_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimals_to_float(v) for v in obj]
    return obj


def ensure_infra() -> CloudStatus:
    """Create every resource Saans needs, idempotently."""
    status = CloudStatus(mode="real AWS" if USE_REAL_AWS else "LocalStack")
    detail: dict[str, str] = {}

    try:
        ddb = _client("dynamodb")
        try:
            ddb.create_table(
                TableName=TABLE,
                KeySchema=[
                    {"AttributeName": "school", "KeyType": "HASH"},
                    {"AttributeName": "day", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "school", "AttributeType": "S"},
                    {"AttributeName": "day", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            detail["dynamodb"] = f"created table {TABLE}"
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceInUseException":
                raise
            detail["dynamodb"] = f"table {TABLE} already present"
        status.dynamodb = True
    except (EndpointConnectionError, ClientError, Exception) as e:
        detail["dynamodb"] = f"unavailable: {type(e).__name__}"

    try:
        s3 = _client("s3")
        try:
            kwargs: dict[str, Any] = {"Bucket": BUCKET}
            if REGION != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": REGION}
            s3.create_bucket(**kwargs)
            detail["s3"] = f"created bucket {BUCKET}"
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise
            detail["s3"] = f"bucket {BUCKET} already present"
        status.s3 = True
    except Exception as e:
        detail["s3"] = f"unavailable: {type(e).__name__}"

    try:
        events = _client("events")
        events.put_rule(
            Name=RULE,
            ScheduleExpression=MORNING_CRON,
            State="ENABLED",
            Description="Decide the day's air protocol before 07:00 IST",
        )
        detail["eventbridge"] = f"rule {RULE} @ {MORNING_CRON} (05:45 IST)"
        status.eventbridge = True
    except Exception as e:
        detail["eventbridge"] = f"unavailable: {type(e).__name__}"

    try:
        ses = _client("ses")
        ses.verify_email_identity(EmailAddress=SENDER)
        detail["ses"] = f"sender {SENDER} verified"
        status.ses = True
    except Exception as e:
        detail["ses"] = f"unavailable: {type(e).__name__}"

    status.detail = detail
    return status


def put_decision(decision_json: dict) -> str:
    """Append one morning's decision to the ledger."""
    ddb = _client("dynamodb")
    from boto3.dynamodb.types import TypeSerializer

    serializer = TypeSerializer()
    item = _floats_to_decimal(
        {
            "school": decision_json["school"],
            "day": decision_json["day"],
            "decided_at": decision_json["decided_at"],
            "protocol_sha256": decision_json["protocol_sha256"],
            "evidence_sha256": decision_json["evidence_sha256"],
            "total_dose_saved": decision_json["total_dose_saved"],
            "children_affected": decision_json["children_affected"],
            "register_affected": decision_json["register_affected"],
            # The full record, so the ledger is self-contained evidence
            # rather than a pointer to state that may have moved on.
            "record": decision_json,
        }
    )
    ddb.put_item(
        TableName=TABLE,
        Item={k: serializer.serialize(v) for k, v in item.items()},
    )
    return f"dynamodb://{TABLE}/{decision_json['school']}/{decision_json['day']}"


def get_decision(school: str, day: str) -> dict | None:
    ddb = _client("dynamodb")
    from boto3.dynamodb.types import TypeDeserializer

    d = TypeDeserializer()
    r = ddb.get_item(
        TableName=TABLE,
        Key={"school": {"S": school}, "day": {"S": day}},
    )
    if "Item" not in r:
        return None
    item = {k: d.deserialize(v) for k, v in r["Item"].items()}
    return _decimals_to_float(item)


def ledger(school: str, limit: int = 30) -> list[dict]:
    """Every decision on file for this school, newest first."""
    ddb = _client("dynamodb")
    from boto3.dynamodb.types import TypeDeserializer

    d = TypeDeserializer()
    r = ddb.query(
        TableName=TABLE,
        KeyConditionExpression="school = :s",
        ExpressionAttributeValues={":s": {"S": school}},
        ScanIndexForward=False,
        Limit=limit,
    )
    out = []
    for raw in r.get("Items", []):
        item = {k: d.deserialize(v) for k, v in raw.items()}
        out.append(_decimals_to_float(item))
    return out


def put_notice(day: str, html: str) -> str:
    """Store the notice exactly as it went home."""
    key = f"notices/{day}.html"
    _client("s3").put_object(
        Bucket=BUCKET,
        Key=key,
        Body=html.encode(),
        ContentType="text/html; charset=utf-8",
        Metadata={"stored-at": datetime.now().isoformat(timespec="seconds")},
    )
    return f"s3://{BUCKET}/{key}"


def get_notice(day: str) -> str | None:
    try:
        r = _client("s3").get_object(Bucket=BUCKET, Key=f"notices/{day}.html")
        return r["Body"].read().decode()
    except Exception:
        return None


def send_notice(recipients: list[str], subject: str, html: str) -> dict:
    """Deliver the morning notice.

    On LocalStack this is a real SES API call that really is accepted and
    really is retrievable from the SES sandbox, so the delivery path is
    exercised rather than stubbed.
    """
    ses = _client("ses")
    r = ses.send_email(
        Source=SENDER,
        Destination={"ToAddresses": recipients},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
        },
    )
    return {"message_id": r["MessageId"], "recipients": recipients}


def sent_messages() -> list[dict]:
    """What SES actually accepted, read back as proof of delivery."""
    try:
        import httpx

        r = httpx.get(f"{ENDPOINT}/_aws/ses", timeout=5.0)
        r.raise_for_status()
        data = r.json()
        msgs = data.get("messages", data if isinstance(data, list) else [])
        return msgs
    except Exception:
        return []
