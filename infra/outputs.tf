output "api_url" {
  description = "Base URL of the API."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "upload_bucket" {
  description = "S3 bucket that receives uploaded files."
  value       = aws_s3_bucket.uploads.bucket
}

output "table_name" {
  description = "DynamoDB table holding jobs and records."
  value       = aws_dynamodb_table.main.name
}

output "queue_url" {
  description = "Queue of files waiting to be processed."
  value       = aws_sqs_queue.uploads.url
}

output "dead_letter_queue_url" {
  description = "Queue holding messages that failed every retry."
  value       = aws_sqs_queue.dlq.url
}

output "alerts_topic_arn" {
  description = "SNS topic that alarms publish to."
  value       = aws_sns_topic.alerts.arn
}

output "function_names" {
  description = "Lambda function name for each entry in local.functions."
  value       = { for key, fn in aws_lambda_function.fn : key => fn.function_name }
}
