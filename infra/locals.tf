data "aws_caller_identity" "current" {}

locals {
  name = "${var.project_name}-${var.environment}"

  # S3 bucket names are global across all AWS accounts; the account id makes this one unique
  bucket_name = "${local.name}-uploads-${data.aws_caller_identity.current.account_id}"
  uploads_arn = "${aws_s3_bucket.uploads.arn}/uploads/*"

  # Used by both the function and the queue (see the visibility timeout in sqs.tf)
  processor_timeout = 60

  # One entry per Lambda function. Each becomes a function, its own IAM role and a log group.
  # Entries with a route also get an API Gateway route; "processor" has none because SQS,
  # not HTTP, triggers it. "statements" is everything that function may do, and nothing more.
  functions = {
    upload = {
      handler = "pipeline.api.create_upload"
      route   = "POST /uploads"
      timeout = 5
      memory  = 128

      statements = [
        {
          actions   = ["dynamodb:PutItem"]
          resources = [aws_dynamodb_table.main.arn]
        },
        {
          # Needed to sign upload URLs: a presigned URL can do only what its signer can
          actions   = ["s3:PutObject"]
          resources = [local.uploads_arn]
        },
      ]
    }

    job = {
      handler = "pipeline.api.get_job"
      route   = "GET /jobs/{job_id}"
      timeout = 5
      memory  = 128

      statements = [
        {
          actions   = ["dynamodb:GetItem"]
          resources = [aws_dynamodb_table.main.arn]
        },
      ]
    }

    records = {
      handler = "pipeline.api.list_records"
      route   = "GET /jobs/{job_id}/records"
      timeout = 5
      memory  = 128

      statements = [
        {
          actions   = ["dynamodb:GetItem", "dynamodb:Query"]
          resources = [aws_dynamodb_table.main.arn]
        },
      ]
    }

    processor = {
      handler = "pipeline.processor.handler"
      route   = null
      timeout = local.processor_timeout
      memory  = 256

      statements = [
        {
          actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
          resources = [aws_sqs_queue.uploads.arn]
        },
        {
          actions   = ["s3:GetObject"]
          resources = [local.uploads_arn]
        },
        {
          actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:BatchWriteItem"]
          resources = [aws_dynamodb_table.main.arn]
        },
      ]
    }
  }

  # Only the functions that sit behind an HTTP route
  api_functions = { for key, fn in local.functions : key => fn if fn.route != null }
}
