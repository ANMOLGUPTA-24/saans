"""Remove everything aws_deploy.py created.

    python deploy/aws_destroy.py --region ap-south-1

A deploy script without a teardown script is how a student ends up with a
bill. Everything Saans creates is inside the free tier, but "inside the
free tier" is not the same as "gone", so this exists and is tested.

The notices bucket is emptied before deletion, because S3 refuses to
delete a bucket with objects in it - and those objects are the notices
that went home, so it asks first.
"""
from __future__ import annotations

import argparse

FUNCTION = "saans-protocol"
ROLE = "saans-lambda-role"
POLICY = "saans-lambda-policy"
TABLE = "saans-decision-ledger"
RULE = "saans-morning-protocol"


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="ap-south-1")
    ap.add_argument(
        "--keep-ledger",
        action="store_true",
        help="leave the DynamoDB table and the notices bucket in place",
    )
    ap.add_argument("--yes", action="store_true", help="do not ask")
    args = ap.parse_args()

    import boto3

    account = boto3.client("sts", region_name=args.region).get_caller_identity()[
        "Account"
    ]
    bucket = f"saans-notices-{account}"

    print(f"\nThis removes from account {account} in {args.region}:")
    print(f"  lambda function   {FUNCTION} (and its Function URL)")
    print(f"  eventbridge rule  {RULE}")
    print(f"  iam role          {ROLE}")
    if not args.keep_ledger:
        print(f"  dynamodb table    {TABLE}   <- the decision ledger")
        print(f"  s3 bucket         {bucket}  <- every notice that went home")
    if not args.yes and input("\nproceed? [y/N] ").strip().lower() != "y":
        raise SystemExit("nothing removed")
    print()

    events = boto3.client("events", region_name=args.region)
    try:
        events.remove_targets(Rule=RULE, Ids=["saans-run"])
        events.delete_rule(Name=RULE)
        log(f"removed rule {RULE}")
    except Exception as e:
        log(f"rule: {type(e).__name__}")

    lam = boto3.client("lambda", region_name=args.region)
    try:
        lam.delete_function_url_config(FunctionName=FUNCTION)
        log("removed Function URL")
    except Exception as e:
        log(f"function url: {type(e).__name__}")
    try:
        lam.delete_function(FunctionName=FUNCTION)
        log(f"removed function {FUNCTION}")
    except Exception as e:
        log(f"function: {type(e).__name__}")

    if not args.keep_ledger:
        s3 = boto3.client("s3", region_name=args.region)
        try:
            token = None
            removed = 0
            while True:
                kw = {"Bucket": bucket}
                if token:
                    kw["ContinuationToken"] = token
                page = s3.list_objects_v2(**kw)
                keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
                if keys:
                    s3.delete_objects(Bucket=bucket, Delete={"Objects": keys})
                    removed += len(keys)
                token = page.get("NextContinuationToken")
                if not page.get("IsTruncated"):
                    break
            s3.delete_bucket(Bucket=bucket)
            log(f"removed bucket {bucket} ({removed} notices)")
        except Exception as e:
            log(f"bucket: {type(e).__name__}")

        try:
            boto3.client("dynamodb", region_name=args.region).delete_table(
                TableName=TABLE
            )
            log(f"removed table {TABLE}")
        except Exception as e:
            log(f"table: {type(e).__name__}")

    iam = boto3.client("iam", region_name=args.region)
    try:
        iam.delete_role_policy(RoleName=ROLE, PolicyName=POLICY)
        iam.delete_role(RoleName=ROLE)
        log(f"removed role {ROLE}")
    except Exception as e:
        log(f"role: {type(e).__name__}")

    print("\ndone. Nothing left running.\n")


if __name__ == "__main__":
    main()
