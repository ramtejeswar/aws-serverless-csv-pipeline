"""The API handlers and the SQS processor working together, against fake DynamoDB and S3."""
import json
from urllib.parse import parse_qs, urlparse

import pytest

from conftest import API_DOMAIN, BUCKET, SAMPLE_CSV, http_event, sqs_event
from pipeline import api, processor, storage, store

HEADER = "order_id,customer_email,amount,currency,order_date\n"


def start_upload(body='{"filename": "orders.csv"}'):
    response = api.create_upload(http_event("POST", "/uploads", body=body), None)
    return response["statusCode"], json.loads(response["body"])


def upload(aws, content):
    """Create a job and put the file in S3, as a client would with the presigned URL."""
    _, created = start_upload()
    key = storage.object_key(created["job_id"])
    aws.s3.put_object(Bucket=BUCKET, Key=key, Body=content)
    return created["job_id"], key


def job_status(job_id):
    response = api.get_job(http_event("GET", f"/jobs/{job_id}", job_id=job_id), None)
    return response["statusCode"], json.loads(response["body"])


def records_page(job_id, **query):
    event = http_event("GET", f"/jobs/{job_id}/records", job_id=job_id, query=query or None)
    response = api.list_records(event, None)
    return response["statusCode"], json.loads(response["body"])


def sample_csv():
    with open(SAMPLE_CSV, "rb") as handle:
        return handle.read()


# --- POST /uploads ---------------------------------------------------------

def test_create_upload_returns_job_and_presigned_url():
    status, body = start_upload()
    assert status == 201
    assert body["status_url"] == f"https://{API_DOMAIN}/jobs/{body['job_id']}"

    url = urlparse(body["upload_url"])
    assert url.netloc == f"{BUCKET}.s3.us-east-1.amazonaws.com"
    assert url.path == f"/uploads/{body['job_id']}.csv"
    query = parse_qs(url.query)
    assert query["X-Amz-Expires"] == ["300"] and "X-Amz-Signature" in query

    assert job_status(body["job_id"])[1]["status"] == "PENDING_UPLOAD"


@pytest.mark.parametrize("body", [None, "", "{}"])
def test_filename_is_optional(body):
    assert start_upload(body)[0] == 201


@pytest.mark.parametrize("body", ["not json", "[]", '{"filename": 42}', '{"filename": ""}'])
def test_create_upload_rejects_bad_input(body):
    assert start_upload(body)[0] == 400


# --- processing ------------------------------------------------------------

def test_sample_file_end_to_end(aws):
    job_id, key = upload(aws, sample_csv())

    assert processor.handler(sqs_event(key), None) == {"batchItemFailures": []}

    status, job = job_status(job_id)
    assert status == 200
    assert job["status"] == "COMPLETED_WITH_ERRORS"
    assert (job["total_rows"], job["valid_rows"], job["error_rows"]) == (10, 5, 5)
    assert job["errors"][0] == {"line": 5, "error": "customer_email is not a valid email address"}
    assert job["records_url"].endswith(f"/jobs/{job_id}/records")

    _, page = records_page(job_id)
    assert [r["order_id"] for r in page["records"]] == ["ORD-1001", "ORD-1002", "ORD-1003", "ORD-1006", "ORD-1010"]
    assert page["records"][0]["amount"] == "49.99"
    assert page["next"] is None


def test_clean_file_completes_without_errors(aws):
    job_id, key = upload(aws, HEADER + "A1,a@x.io,10.00,USD,2026-01-01\n")
    processor.handler(sqs_event(key), None)
    _, job = job_status(job_id)
    assert job["status"] == "COMPLETED" and job["errors"] == []


@pytest.mark.parametrize("content,reason", [
    (b"name,price\nx,1\n", "Missing required column"),
    (b"\xff\xfe\x00bad", "not UTF-8"),
    ((HEADER + "bad,row\n").encode(), "No valid rows"),
])
def test_unusable_file_fails_the_job_without_retrying(aws, content, reason):
    job_id, key = upload(aws, content)
    assert processor.handler(sqs_event(key), None) == {"batchItemFailures": []}
    _, job = job_status(job_id)
    assert job["status"] == "FAILED" and reason in job["failure_reason"]


def test_oversized_file_fails_the_job(aws, monkeypatch):
    monkeypatch.setattr(storage, "MAX_FILE_BYTES", 10)
    job_id, key = upload(aws, sample_csv())
    processor.handler(sqs_event(key), None)
    assert "larger than" in job_status(job_id)[1]["failure_reason"]


def test_excel_byte_order_mark_is_ignored(aws):
    job_id, key = upload(aws, b"\xef\xbb\xbf" + (HEADER + "A1,a@x.io,1,USD,2026-01-01\n").encode())
    processor.handler(sqs_event(key), None)
    assert job_status(job_id)[1]["status"] == "COMPLETED"


def test_processing_twice_gives_the_same_result(aws):
    """SQS delivers at-least-once, so a redelivered message must not duplicate anything."""
    job_id, key = upload(aws, sample_csv())
    processor.handler(sqs_event(key), None)
    first = (job_status(job_id)[1], records_page(job_id)[1])

    processor.handler(sqs_event(key), None)  # duplicate delivery after success: skipped
    assert (job_status(job_id)[1], records_page(job_id)[1]) == first

    store.mark_processing(job_id)  # as if a first attempt had crashed half-way
    processor.handler(sqs_event(key), None)
    again = job_status(job_id)[1]
    assert (again["status"], again["valid_rows"]) == ("COMPLETED_WITH_ERRORS", 5)
    assert records_page(job_id)[1] == first[1]


def test_a_failing_message_is_reported_and_the_rest_still_succeed(aws):
    good_job, good_key = upload(aws, sample_csv())
    _, created = start_upload()
    missing_key = storage.object_key(created["job_id"])  # job exists but the object does not

    result = processor.handler(sqs_event(missing_key, good_key), None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "msg-0"}]}
    assert job_status(good_job)[1]["status"] == "COMPLETED_WITH_ERRORS"
    assert job_status(created["job_id"])[1]["status"] == "PROCESSING"


def test_messages_that_need_no_work_are_acknowledged(aws):
    aws.s3.put_object(Bucket=BUCKET, Key="uploads/stray.csv", Body=b"x")
    unknown_job = "uploads/00000000-0000-4000-8000-000000000000.csv"
    event = sqs_event("uploads/stray.csv", unknown_job)
    event["Records"].append({"messageId": "test", "body": json.dumps({"Event": "s3:TestEvent"})})
    assert processor.handler(event, None) == {"batchItemFailures": []}


def test_malformed_message_is_reported_as_failed():
    event = {"Records": [{"messageId": "m1", "body": "not json"}]}
    assert processor.handler(event, None) == {"batchItemFailures": [{"itemIdentifier": "m1"}]}


# --- GET /jobs/{id} and /records -------------------------------------------

@pytest.mark.parametrize("job_id", ["nope", "00000000-0000-4000-8000-000000000000"])
def test_unknown_job_is_404(job_id):
    assert job_status(job_id)[0] == 404
    assert records_page(job_id)[0] == 404


def test_records_are_paginated(aws):
    rows = "".join(f"A{n:02d},a@x.io,1,USD,2026-01-01\n" for n in range(7))
    job_id, key = upload(aws, HEADER + rows)
    processor.handler(sqs_event(key), None)

    seen, token, pages = [], None, 0
    while True:
        query = {"limit": "3", **({"next": token} if token else {})}
        status, page = records_page(job_id, **query)
        assert status == 200 and len(page["records"]) <= 3
        seen += [r["order_id"] for r in page["records"]]
        token, pages = page["next"], pages + 1
        if token is None:
            break
    assert seen == [f"A{n:02d}" for n in range(7)]
    assert pages == 3


def test_bad_paging_parameters_are_400(aws):
    job_a, key_a = upload(aws, HEADER + "A1,a@x.io,1,USD,2026-01-01\nA2,a@x.io,1,USD,2026-01-01\n")
    job_b, _ = upload(aws, b"")
    processor.handler(sqs_event(key_a), None)
    token = records_page(job_a, limit="1")[1]["next"]
    assert token

    assert records_page(job_a, limit="0")[0] == 400
    assert records_page(job_a, limit="101")[0] == 400
    assert records_page(job_a, limit="abc")[0] == 400
    assert records_page(job_a, next="garbage!")[0] == 400
    assert records_page(job_b, next=token)[0] == 400  # a token from another job is refused
