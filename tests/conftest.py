"""Shared fixtures. moto fakes DynamoDB and S3 in memory: no AWS account or network needed."""
import json
import os
import sys
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from pipeline import storage, store  # noqa: E402  (needs the sys.path entry above)

TABLE_NAME = "test-data"
BUCKET = "test-uploads"
API_DOMAIN = "abc123.execute-api.us-east-1.amazonaws.com"
SAMPLE_CSV = os.path.join(os.path.dirname(__file__), "..", "samples", "orders.csv")


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    for name, value in {
        "TABLE_NAME": TABLE_NAME,
        "UPLOAD_BUCKET": BUCKET,
        "AWS_REGION": "us-east-1",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
    }.items():
        monkeypatch.setenv(name, value)
    store.table.cache_clear()  # make the code build its clients inside the mock
    storage.client.cache_clear()
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket=BUCKET)
        yield SimpleNamespace(table=boto3.resource("dynamodb").Table(TABLE_NAME), s3=s3)
    store.table.cache_clear()
    storage.client.cache_clear()


def http_event(method, path, body=None, job_id=None, query=None):
    """A minimal API Gateway HTTP API event (payload format 2.0)."""
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "requestContext": {"domainName": API_DOMAIN, "http": {"method": method, "path": path}},
        "pathParameters": {"job_id": job_id} if job_id is not None else None,
        "queryStringParameters": query,
        "body": body,
        "isBase64Encoded": False,
    }


def sqs_event(*object_keys):
    """An SQS batch where each message wraps one S3 "object created" notification."""
    return {"Records": [
        {
            "messageId": f"msg-{index}",
            "body": json.dumps({"Records": [{
                "eventName": "ObjectCreated:Put",
                "s3": {"bucket": {"name": BUCKET}, "object": {"key": key}},
            }]}),
        }
        for index, key in enumerate(object_keys)
    ]}
