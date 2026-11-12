"""Lambda entry points for the HTTP API, one per route."""
import base64
import json
import logging
import re
import uuid

from pipeline import storage, store
from pipeline.http import BadRequest, base_url, json_response, parse_json_body, path_param, query_param

# Lambda is configured for JSON logs (infra/lambda.tf): "extra" fields become top-level keys
logger = logging.getLogger()

JOB_ID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
NOT_FOUND = {"error": "Job not found"}
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


def _valid_job_id(event):
    job_id = path_param(event, "job_id") or ""
    return job_id if JOB_ID.match(job_id) else None


def create_upload(event, context):
    """POST /uploads  {"filename": "orders.csv"}  ->  201 with a job id and a presigned upload URL."""
    try:
        filename = parse_json_body(event).get("filename", "upload.csv")
        if not isinstance(filename, str) or not 1 <= len(filename) <= 255:
            raise BadRequest("Field 'filename' must be a string of 1-255 characters")
    except BadRequest as err:
        return json_response(400, {"error": str(err)})

    job_id = str(uuid.uuid4())  # random and unguessable: knowing the id is what grants access
    key = storage.object_key(job_id)
    store.create_job(job_id, filename, key)
    logger.info("upload_created", extra={"job_id": job_id})

    return json_response(201, {
        "job_id": job_id,
        "upload_url": storage.presigned_upload_url(key),
        "upload_method": "PUT",
        "upload_expires_in": storage.UPLOAD_URL_EXPIRES_SECONDS,
        "max_bytes": storage.MAX_FILE_BYTES,
        "status_url": f"{base_url(event)}/jobs/{job_id}",
    })


def get_job(event, context):
    """GET /jobs/{job_id}  ->  200 with status, counts and the first row errors, or 404."""
    job_id = _valid_job_id(event)
    job = store.get_job(job_id) if job_id else None
    if job is None:
        return json_response(404, NOT_FOUND)
    job["records_url"] = f"{base_url(event)}/jobs/{job_id}/records"
    return json_response(200, job)


def list_records(event, context):
    """GET /jobs/{job_id}/records?limit=25&next=<token>  ->  one page of stored rows."""
    job_id = _valid_job_id(event)
    if job_id is None or store.get_job(job_id) is None:
        return json_response(404, NOT_FOUND)
    try:
        limit = _page_size(query_param(event, "limit"))
        start_key = _decode_token(query_param(event, "next"), job_id)
    except BadRequest as err:
        return json_response(400, {"error": str(err)})

    records, last_key = store.list_records(job_id, limit, start_key)
    return json_response(200, {
        "job_id": job_id,
        "records": records,
        "next": _encode_token(last_key),  # null on the last page
    })


def _page_size(raw):
    if raw is None:
        return DEFAULT_PAGE_SIZE
    if not raw.isdigit() or not 1 <= int(raw) <= MAX_PAGE_SIZE:
        raise BadRequest(f"Query parameter 'limit' must be a number from 1 to {MAX_PAGE_SIZE}")
    return int(raw)


def _encode_token(key):
    """DynamoDB's LastEvaluatedKey as an opaque URL-safe string."""
    if not key:
        return None
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode().rstrip("=")


def _decode_token(token, job_id):
    if token is None:
        return None
    try:
        key = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        valid = (
            isinstance(key, dict)
            and set(key) == {"pk", "sk"}
            and key["pk"] == store.partition(job_id)  # a token can never point at another job
            and isinstance(key["sk"], str)
            and key["sk"].startswith(store.RECORD_PREFIX)
        )
    except (ValueError, UnicodeDecodeError):
        valid = False
    if not valid:
        raise BadRequest("Query parameter 'next' is not a valid page token")
    return key
