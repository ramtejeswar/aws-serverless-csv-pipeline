"""The background worker: SQS delivers "a file was uploaded" messages, this processes them.

Delivery is at-least-once: the same message can arrive twice, and a message whose
processing crashes is redelivered. So processing must be idempotent - doing it again
must give the same end state. Here that holds because records are keyed by order_id
(re-writing overwrites) and job counts are SET to totals (never incremented).
"""
import json
import logging
from urllib.parse import unquote_plus

from pipeline import orders, storage, store
from pipeline.errors import FileRejected

logger = logging.getLogger()


def handler(event, context):
    """Process a batch of SQS messages and report which ones failed.

    Returning batchItemFailures (instead of raising) means only the failed messages go
    back to the queue; the ones that succeeded are deleted. After max_receive_count
    failed attempts SQS moves a message to the dead-letter queue, which raises an alarm.
    """
    failures = []
    for message in event.get("Records", []):
        try:
            _handle_message(message)
        except Exception:
            logger.exception("message_failed", extra={"message_id": message["messageId"]})
            failures.append({"itemIdentifier": message["messageId"]})
    return {"batchItemFailures": failures}


def _handle_message(message):
    body = json.loads(message["body"])
    if body.get("Event") == "s3:TestEvent":
        return  # S3 sends this once when the bucket notification is first configured
    for record in body.get("Records", []):
        # Object keys arrive URL-encoded in S3 events
        process_object(unquote_plus(record["s3"]["object"]["key"]))


def process_object(key):
    job_id = storage.job_id_from_key(key)
    job = store.get_job(job_id) if job_id else None
    if job is None:
        logger.warning("object_without_job", extra={"object_key": key})
        return
    if job["status"] in store.FINISHED:
        logger.info("duplicate_delivery_skipped", extra={"job_id": job_id})
        return

    store.mark_processing(job_id)
    try:
        result = orders.parse(storage.read_text(key))
    except FileRejected as err:
        # Permanent problem with the file: record it and do NOT retry
        store.finish_job(job_id, store.FAILED, failure_reason=str(err))
        logger.info("job_failed", extra={"job_id": job_id, "reason": str(err)})
        return

    store.put_records(job_id, result.records)

    if not result.records:
        status, reason = store.FAILED, "No valid rows in file"
    elif result.error_count:
        status, reason = store.COMPLETED_WITH_ERRORS, None
    else:
        status, reason = store.COMPLETED, None
    store.finish_job(
        job_id,
        status,
        total_rows=result.total_rows,
        valid_rows=len(result.records),
        error_rows=result.error_count,
        errors=result.errors,
        failure_reason=reason,
    )
    logger.info("job_finished", extra={
        "job_id": job_id,
        "status": status,
        "valid_rows": len(result.records),
        "error_rows": result.error_count,
    })
