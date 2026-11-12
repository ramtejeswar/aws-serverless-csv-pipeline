# Messages that failed max_receive_count times end up here, kept 14 days for investigation
resource "aws_sqs_queue" "dlq" {
  name                      = "${local.name}-uploads-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "uploads" {
  name = "${local.name}-uploads"

  # While one Lambda invocation works on a message, SQS hides it from other consumers for
  # this long. It must outlast the function timeout, or a slow run gets processed twice.
  # AWS recommends at least 6x the function timeout for Lambda event sources.
  visibility_timeout_seconds = local.processor_timeout * 6
  message_retention_seconds  = 345600

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}

# Resource-based policy on the queue: only S3, only for this bucket, only from this account
data "aws_iam_policy_document" "s3_to_queue" {
  statement {
    sid       = "AllowBucketNotifications"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.uploads.arn]

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.uploads.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sqs_queue_policy" "uploads" {
  queue_url = aws_sqs_queue.uploads.id
  policy    = data.aws_iam_policy_document.s3_to_queue.json
}

# Lambda polls the queue and invokes the processor with batches of messages
resource "aws_lambda_event_source_mapping" "uploads" {
  event_source_arn = aws_sqs_queue.uploads.arn
  function_name    = aws_lambda_function.fn["processor"].arn
  batch_size       = 5

  # Lets the function report failed messages one by one instead of failing the whole batch
  function_response_types = ["ReportBatchItemFailures"]

  # At most 2 processor instances at once, so a flood of uploads cannot run up a bill
  scaling_config {
    maximum_concurrency = 2
  }

  depends_on = [aws_iam_role_policy.fn]
}
