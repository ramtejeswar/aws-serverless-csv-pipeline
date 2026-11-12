# ---------------------------------------------------------------------------
# DynamoDB: jobs and their records in one table (item shapes: src/pipeline/store.py)
# ---------------------------------------------------------------------------
resource "aws_dynamodb_table" "main" {
  name         = "${local.name}-data"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  # DynamoDB deletes items some time after the epoch-seconds value in expires_at has passed
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

# ---------------------------------------------------------------------------
# S3: private bucket for uploaded files (encrypted at rest by default with SSE-S3)
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "uploads" {
  bucket = local.bucket_name

  # Lets `terraform destroy` delete the bucket even when it still holds files.
  # Right for a learning project; remove it for data you cannot afford to lose.
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    id     = "expire-uploads"
    status = "Enabled"

    filter {
      prefix = "uploads/"
    }

    expiration {
      days = var.data_retention_days
    }
  }
}

# "A .csv object was created under uploads/" -> put a message on the queue
resource "aws_s3_bucket_notification" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  queue {
    queue_arn     = aws_sqs_queue.uploads.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "uploads/"
    filter_suffix = ".csv"
  }

  # S3 checks that it may send to the queue at the moment the notification is created
  depends_on = [aws_sqs_queue_policy.uploads]
}
