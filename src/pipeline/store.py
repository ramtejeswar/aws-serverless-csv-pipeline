"""DynamoDB access. One table holds both jobs and their records (single-table design).

    pk               sk                 item
    JOB#<job_id>     META               the job: status, counts, first row errors
    JOB#<job_id>     ORDER#<order_id>   one valid row from the file

A job and all its records share a partition key, so "give me this job's records" is one
Query. Every item carries expires_at (epoch seconds); DynamoDB TTL deletes it afterwards.
"""
import os
import time
from datetime import datetime, timezone
from functools import lru_cache

import boto3
from boto3.dynamodb.conditions import Key

PENDING_UPLOAD = "PENDING_UPLOAD"
PROCESSING = "PROCESSING"
COMPLETED = "COMPLETED"
COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
FAILED = "FAILED"
FINISHED = (COMPLETED, COMPLETED_WITH_ERRORS, FAILED)

RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "7"))
RECORD_PREFIX = "ORDER#"


@lru_cache(maxsize=1)
def table():
    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _expires_at():
    return int(time.time()) + RETENTION_DAYS * 24 * 3600


def partition(job_id):
    return f"JOB#{job_id}"


def _job_key(job_id):
    return {"pk": partition(job_id), "sk": "META"}


def create_job(job_id, filename, object_key):
    table().put_item(
        Item={
            **_job_key(job_id),
            "job_id": job_id,
            "status": PENDING_UPLOAD,
            "filename": filename,
            "object_key": object_key,
            "created_at": _now(),
            "expires_at": _expires_at(),
        },
        ConditionExpression="attribute_not_exists(pk)",
    )


def get_job(job_id):
    """The job as plain JSON-safe types, or None."""
    item = table().get_item(Key=_job_key(job_id), ConsistentRead=True).get("Item")
    if not item:
        return None
    job = {
        "job_id": item["job_id"],
        "status": item["status"],
        "filename": item.get("filename"),
        "created_at": item.get("created_at"),
        "completed_at": item.get("completed_at"),
    }
    if item["status"] in FINISHED:
        job.update(
            total_rows=int(item.get("total_rows", 0)),
            valid_rows=int(item.get("valid_rows", 0)),
            error_rows=int(item.get("error_rows", 0)),
            errors=[{"line": int(e["line"]), "error": e["error"]} for e in item.get("errors", [])],
        )
    if item.get("failure_reason"):
        job["failure_reason"] = item["failure_reason"]
    return job


def mark_processing(job_id):
    # "status" is a DynamoDB reserved word, so it needs the #s placeholder
    table().update_item(
        Key=_job_key(job_id),
        UpdateExpression="SET #s = :status, started_at = :now",
        ConditionExpression="attribute_exists(pk)",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": PROCESSING, ":now": _now()},
    )


def finish_job(job_id, status, total_rows=0, valid_rows=0, error_rows=0, errors=(), failure_reason=None):
    """Record the outcome. Counts are SET, not added, so running this twice is harmless."""
    expression = (
        "SET #s = :status, completed_at = :now, total_rows = :total, "
        "valid_rows = :valid, error_rows = :bad, errors = :errors"
    )
    values = {
        ":status": status,
        ":now": _now(),
        ":total": total_rows,
        ":valid": valid_rows,
        ":bad": error_rows,
        ":errors": list(errors),
    }
    if failure_reason:
        expression += ", failure_reason = :reason"
        values[":reason"] = failure_reason
    table().update_item(
        Key=_job_key(job_id),
        UpdateExpression=expression,
        ConditionExpression="attribute_exists(pk)",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues=values,
    )


def put_records(job_id, records):
    """Store valid rows. The key is the order_id, so re-writing the same file overwrites
    the same items instead of duplicating them (this is what makes retries safe)."""
    expires_at = _expires_at()
    # batch_writer groups puts into BatchWriteItem calls of 25 and retries unprocessed items
    with table().batch_writer() as batch:
        for record in records:
            batch.put_item(Item={
                "pk": partition(job_id),
                "sk": f"{RECORD_PREFIX}{record['order_id']}",
                **record,
                "expires_at": expires_at,
            })


def list_records(job_id, limit, start_key=None):
    """One page of a job's records, plus the key to continue from (None on the last page)."""
    query = {
        "KeyConditionExpression": Key("pk").eq(partition(job_id)) & Key("sk").begins_with(RECORD_PREFIX),
        "Limit": limit,
    }
    if start_key:
        query["ExclusiveStartKey"] = start_key
    page = table().query(**query)
    records = [
        {
            "order_id": item["order_id"],
            "customer_email": item["customer_email"],
            "amount": str(item["amount"]),  # string keeps the exact decimal value in JSON
            "currency": item["currency"],
            "order_date": item["order_date"],
        }
        for item in page["Items"]
    ]
    return records, page.get("LastEvaluatedKey")
