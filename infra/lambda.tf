# All functions ship in one zip of src/. Terraform rebuilds it, and redeploys the
# functions, whenever any source file changes (source_code_hash below).
data "archive_file" "app" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/.build/app.zip"
  excludes    = ["**/__pycache__/**"]
}

# ---------------------------------------------------------------------------
# IAM: one role per function, built from its "statements" in locals.tf
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fn" {
  for_each = local.functions

  name               = "${local.name}-${each.key}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "fn" {
  for_each = local.functions

  # One IAM statement per entry in this function's "statements" list
  dynamic "statement" {
    for_each = each.value.statements

    content {
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }

  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.fn[each.key].arn}:*"]
  }
}

resource "aws_iam_role_policy" "fn" {
  for_each = local.functions

  name   = "${local.name}-${each.key}"
  role   = aws_iam_role.fn[each.key].id
  policy = data.aws_iam_policy_document.fn[each.key].json
}

# ---------------------------------------------------------------------------
# Functions and their logs
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "fn" {
  for_each = local.functions

  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "fn" {
  for_each = local.functions

  function_name    = "${local.name}-${each.key}"
  description      = each.value.route != null ? "${each.value.route} for ${local.name}" : "Queue worker for ${local.name}"
  role             = aws_iam_role.fn[each.key].arn
  handler          = each.value.handler
  runtime          = var.lambda_runtime
  architectures    = [var.lambda_architecture]
  memory_size      = each.value.memory
  timeout          = each.value.timeout
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256

  environment {
    variables = {
      TABLE_NAME     = aws_dynamodb_table.main.name
      UPLOAD_BUCKET  = aws_s3_bucket.uploads.bucket
      RETENTION_DAYS = tostring(var.data_retention_days)
    }
  }

  # Structured JSON logs; Lambda also filters by level, so no log-level code is needed
  logging_config {
    log_format            = "JSON"
    application_log_level = var.log_level
    system_log_level      = "INFO"
  }

  # Log group and permissions must exist before the first invocation tries to log
  depends_on = [aws_cloudwatch_log_group.fn, aws_iam_role_policy.fn]
}
