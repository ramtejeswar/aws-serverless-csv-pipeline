"""S3 access: presigned upload URLs and reading uploaded files."""
import os
import re
from functools import lru_cache

import boto3
from botocore.config import Config

from pipeline.errors import FileRejected

UPLOAD_PREFIX = "uploads/"
UPLOAD_URL_EXPIRES_SECONDS = 300
MAX_FILE_BYTES = 5 * 1024 * 1024

# Only keys this service generated are processed: uploads/<uuid4>.csv
OBJECT_KEY = re.compile(r"^uploads/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.csv$")


@lru_cache(maxsize=1)
def client():
    region = os.environ["AWS_REGION"]  # set automatically inside Lambda
    # Regional endpoint + SigV4: presigned URLs for a brand-new bucket otherwise point at the
    # global endpoint, which answers with a redirect until the bucket's DNS has propagated.
    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=f"https://s3.{region}.amazonaws.com",
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )


def bucket():
    return os.environ["UPLOAD_BUCKET"]


def object_key(job_id):
    return f"{UPLOAD_PREFIX}{job_id}.csv"


def job_id_from_key(key):
    match = OBJECT_KEY.match(key)
    return match.group(1) if match else None


def presigned_upload_url(key):
    """A URL that lets its holder PUT exactly this one object, for a few minutes.

    The file goes straight from the client to S3, so it never passes through API Gateway
    (10 MB limit) or Lambda (6 MB limit), and the bucket itself stays private.
    """
    return client().generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket(), "Key": key},
        ExpiresIn=UPLOAD_URL_EXPIRES_SECONDS,
    )


def read_text(key):
    obj = client().get_object(Bucket=bucket(), Key=key)
    # A presigned PUT cannot cap the upload size, so the limit is enforced here
    if obj["ContentLength"] > MAX_FILE_BYTES:
        raise FileRejected(f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    try:
        return obj["Body"].read().decode("utf-8-sig")  # -sig drops Excel's byte-order mark
    except UnicodeDecodeError:
        raise FileRejected("File is not UTF-8 text") from None
