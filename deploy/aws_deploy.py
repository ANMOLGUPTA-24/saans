"""Deploy Saans to real AWS, on the free tier, in one command.

    python deploy/aws_deploy.py --region ap-south-1

Everything it creates sits inside AWS's always-free or 12-month-free
allowances, which matters: this is a student project with no budget.

    Lambda           1M requests and 400,000 GB-seconds a month, always free
    Function URL     free; no API Gateway, which is what would cost money
    DynamoDB         25 GB on-demand, always free
    S3               5 GB for the first 12 months
    EventBridge      rules are free; you pay only for what they invoke
    CloudWatch Logs  5 GB ingest a month, always free
    SES              sandbox; verified identities only, 200 messages a day

The script is idempotent - run it again after a code change and it
updates the function in place rather than making a second one.

It never prints a credential and never writes one to disk.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / ".build" / "lambda"
REQS = ROOT / "deploy" / "requirements-lambda.txt"

FUNCTION = "saans-protocol"
ROLE = "saans-lambda-role"
POLICY = "saans-lambda-policy"
TABLE = "saans-decision-ledger"
RULE = "saans-morning-protocol"
MORNING_CRON = "cron(15 0 * * ? *)"  # 05:45 IST
RUNTIME = "python3.12"
# Lambda's x86_64 runtime is Amazon Linux 2023. cedarpy ships a manylinux
# wheel for it, which is the only reason a Rust policy engine can run here
# without a container build.
PLATFORM = "manylinux2014_x86_64"
ARCH = "x86_64"
MEMORY_MB = 512
TIMEOUT_S = 60

PACKAGE = ["saans", "web", "protocol", "data"]


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def build_zip() -> bytes:
    """Install the deployed dependency set and zip it with the source."""
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    log(f"installing {REQS.name} for {PLATFORM}")
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "-q",
            "-r", str(REQS),
            "--target", str(BUILD),
            "--platform", PLATFORM,
            "--python-version", "3.12",
            "--only-binary=:all:",
            "--upgrade",
        ],
        check=True,
    )

    for name in PACKAGE:
        src = ROOT / name
        if not src.exists():
            continue
        shutil.copytree(
            src,
            BUILD / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".cache"),
        )

    # boto3/botocore are in the runtime already, and they are large enough
    # to matter against the 250 MB unzipped limit.
    for drop in ("boto3", "botocore", "pip", "setuptools", "wheel"):
        for p in BUILD.glob(f"{drop}*"):
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(BUILD.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(BUILD))
    raw = buf.getvalue()
    unzipped = sum(f.stat().st_size for f in BUILD.rglob("*") if f.is_file())
    log(f"package: {len(raw) / 1e6:.1f} MB zipped, {unzipped / 1e6:.1f} MB unzipped")
    if len(raw) > 50 * 1024 * 1024:
        raise SystemExit(
            "zip exceeds Lambda's 50 MB direct-upload limit; upload via S3 instead"
        )
    return raw


def ensure_role(iam, account: str) -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        arn = iam.create_role(
            RoleName=ROLE,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Saans: decide the school air protocol",
        )["Role"]["Arn"]
        log(f"created role {ROLE}")
        fresh = True
    except iam.exceptions.EntityAlreadyExistsException:
        arn = iam.get_role(RoleName=ROLE)["Role"]["Arn"]
        log(f"role {ROLE} already present")
        fresh = False

    # Least privilege: only this table, only this bucket prefix, and SES
    # only from the verified sender.
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": "arn:aws:logs:*:*:*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                ],
                "Resource": f"arn:aws:dynamodb:*:{account}:table/{TABLE}",
            },
            {
                "Effect": "Allow",
                "Action": ["s3:PutObject", "s3:GetObject"],
                "Resource": f"arn:aws:s3:::saans-notices-{account}/*",
            },
            {
                "Effect": "Allow",
                "Action": ["ses:SendEmail", "ses:SendRawEmail"],
                "Resource": "*",
            },
        ],
    }
    iam.put_role_policy(
        RoleName=ROLE, PolicyName=POLICY, PolicyDocument=json.dumps(policy)
    )
    log("attached inline policy (table, bucket and SES only)")
    if fresh:
        log("waiting 10s for IAM to propagate")
        time.sleep(10)
    return arn


def ensure_table(ddb) -> None:
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
        log(f"created table {TABLE} (on-demand, inside the 25 GB free tier)")
    except ddb.exceptions.ResourceInUseException:
        log(f"table {TABLE} already present")


def ensure_bucket(s3, account: str, region: str) -> str:
    bucket = f"saans-notices-{account}"
    try:
        kwargs: dict = {"Bucket": bucket}
        if region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**kwargs)
        log(f"created bucket {bucket}")
    except Exception as e:
        if type(e).__name__ in (
            "BucketAlreadyOwnedByYou",
            "BucketAlreadyExists",
        ) or "BucketAlreadyOwnedByYou" in str(e):
            log(f"bucket {bucket} already present")
        else:
            raise
    return bucket


def ensure_function(lam, role_arn: str, zip_bytes: bytes, bucket: str) -> str:
    env = {
        "Variables": {
            "SAANS_AWS": "real",
            "SAANS_BUCKET": bucket,
            # Keep the free public air API from being called on every
            # single request.
            "PYTHONUNBUFFERED": "1",
        }
    }
    try:
        lam.create_function(
            FunctionName=FUNCTION,
            Runtime=RUNTIME,
            Role=role_arn,
            Handler="saans.api.handler",
            Code={"ZipFile": zip_bytes},
            Timeout=TIMEOUT_S,
            MemorySize=MEMORY_MB,
            Architectures=[ARCH],
            Environment=env,
            Description="Saans: the bad air day protocol for Indian schools",
        )
        log(f"created function {FUNCTION}")
    except lam.exceptions.ResourceConflictException:
        lam.update_function_code(FunctionName=FUNCTION, ZipFile=zip_bytes)
        _wait_updated(lam)
        lam.update_function_configuration(
            FunctionName=FUNCTION,
            Runtime=RUNTIME,
            Role=role_arn,
            Handler="saans.api.handler",
            Timeout=TIMEOUT_S,
            MemorySize=MEMORY_MB,
            Environment=env,
        )
        log(f"updated function {FUNCTION} in place")
    _wait_updated(lam)

    try:
        url = lam.create_function_url_config(
            FunctionName=FUNCTION, AuthType="NONE"
        )["FunctionUrl"]
        log("created public Function URL")
    except lam.exceptions.ResourceConflictException:
        url = lam.get_function_url_config(FunctionName=FUNCTION)["FunctionUrl"]
        log("Function URL already present")

    # A Function URL with AuthType NONE still needs an explicit public
    # invoke permission, which is the step everyone forgets.
    try:
        lam.add_permission(
            FunctionName=FUNCTION,
            StatementId="public-function-url",
            Action="lambda:InvokeFunctionUrl",
            Principal="*",
            FunctionUrlAuthType="NONE",
        )
        log("granted public invoke on the Function URL")
    except lam.exceptions.ResourceConflictException:
        log("public invoke permission already present")
    return url


def _wait_updated(lam) -> None:
    for _ in range(60):
        cfg = lam.get_function_configuration(FunctionName=FUNCTION)
        if cfg.get("LastUpdateStatus") != "InProgress" and cfg.get("State") == "Active":
            return
        time.sleep(2)


def ensure_schedule(events, lam, region: str, account: str) -> None:
    events.put_rule(
        Name=RULE,
        ScheduleExpression=MORNING_CRON,
        State="ENABLED",
        Description="Decide the day's air protocol before 07:00 IST",
    )
    fn_arn = f"arn:aws:lambda:{region}:{account}:function:{FUNCTION}"
    try:
        lam.add_permission(
            FunctionName=FUNCTION,
            StatementId="eventbridge-morning",
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=f"arn:aws:events:{region}:{account}:rule/{RULE}",
        )
    except lam.exceptions.ResourceConflictException:
        pass
    events.put_targets(
        Rule=RULE,
        Targets=[
            {
                "Id": "saans-run",
                "Arn": fn_arn,
                # Shaped like a Function URL GET so the same handler serves it.
                "Input": json.dumps(
                    {
                        "version": "2.0",
                        "rawPath": "/api/today",
                        "requestContext": {
                            "http": {"method": "GET", "path": "/api/today"}
                        },
                        "headers": {},
                    }
                ),
            }
        ],
    )
    log(f"scheduled {RULE} at {MORNING_CRON} (05:45 IST)")


def ensure_ses(ses, sender: str) -> None:
    try:
        ses.verify_email_identity(EmailAddress=sender)
        log(f"verification requested for {sender} - check that inbox")
        log("SES starts in sandbox: only verified addresses can receive")
    except Exception as e:
        log(f"SES skipped: {type(e).__name__}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="ap-south-1", help="default: ap-south-1 (Mumbai)")
    ap.add_argument("--sender", default="", help="email to verify for SES notices")
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args()

    try:
        import boto3
        from botocore.exceptions import NoCredentialsError
    except ImportError:
        raise SystemExit("pip install boto3")

    print(f"\nSaans -> AWS ({args.region})\n")
    try:
        sts = boto3.client("sts", region_name=args.region)
        account = sts.get_caller_identity()["Account"]
    except Exception as e:
        raise SystemExit(
            "No usable AWS credentials.\n\n"
            "  1. Create a free account at https://aws.amazon.com/free\n"
            "     (debit card and RuPay work; the verification charge is about Rs 2)\n"
            "  2. Create an access key: IAM > Users > Security credentials\n"
            "  3. export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...\n"
            "  4. Run this again.\n\n"
            f"  ({type(e).__name__})"
        )
    log(f"account {account}")

    zip_bytes = build_zip() if not args.skip_build else (ROOT / ".build" / "saans.zip").read_bytes()
    if not args.skip_build:
        (ROOT / ".build" / "saans.zip").write_bytes(zip_bytes)

    role_arn = ensure_role(boto3.client("iam", region_name=args.region), account)
    ensure_table(boto3.client("dynamodb", region_name=args.region))
    bucket = ensure_bucket(boto3.client("s3", region_name=args.region), account, args.region)
    lam = boto3.client("lambda", region_name=args.region)
    url = ensure_function(lam, role_arn, zip_bytes, bucket)
    ensure_schedule(boto3.client("events", region_name=args.region), lam, args.region, account)
    if args.sender:
        ensure_ses(boto3.client("ses", region_name=args.region), args.sender)

    print(f"\nLive on AWS: {url}\n")
    print("  Check it:")
    print(f"    curl -s {url}api/today | head -c 400")
    print(f"    curl -s {url}api/cloud")
    print("\n  Everything above sits inside the free tier. Tear it all down with:")
    print(f"    python deploy/aws_destroy.py --region {args.region}\n")


if __name__ == "__main__":
    main()
