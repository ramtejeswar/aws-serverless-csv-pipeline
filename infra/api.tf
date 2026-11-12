resource "aws_apigatewayv2_api" "http" {
  name          = "${local.name}-api"
  description   = "CSV ingestion pipeline (${var.environment})"
  protocol_type = "HTTP"
}

# One access-log line per request: the first place to look when something returns 4xx/5xx
resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${local.name}-access"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.throttle_rate_limit
    throttling_burst_limit = var.throttle_burst_limit
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn

    format = jsonencode({
      requestId        = "$context.requestId"
      requestTime      = "$context.requestTime"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      latencyMs        = "$context.responseLatency"
      integrationError = "$context.integrationErrorMessage"
    })
  }
}

# Route -> integration -> function, for the functions that have a route
resource "aws_apigatewayv2_integration" "fn" {
  for_each = local.api_functions

  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.fn[each.key].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "fn" {
  for_each = local.api_functions

  api_id    = aws_apigatewayv2_api.http.id
  route_key = each.value.route
  target    = "integrations/${aws_apigatewayv2_integration.fn[each.key].id}"
}

# The function's resource-based policy: "API Gateway may invoke me"
resource "aws_lambda_permission" "api_invoke" {
  for_each = local.api_functions

  statement_id  = "AllowInvokeFromApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
