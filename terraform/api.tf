resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/apigateway/${local.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_api" "retail" {
  name                         = "${local.name}-api"
  protocol_type                = "HTTP"
  disable_execute_api_endpoint = false
  cors_configuration {
    allow_origins = ["https://${aws_cloudfront_distribution.frontend.domain_name}"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["authorization", "content-type", "idempotency-key"]
    max_age       = 300
  }
  # Default execute-api HTTPS endpoint, no custom domain or ACM certificate.
}

resource "aws_apigatewayv2_stage" "live" {
  api_id      = aws_apigatewayv2_api.retail.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format = jsonencode({
      requestId        = "$context.requestId", status = "$context.status",
      routeKey         = "$context.routeKey", responseLength = "$context.responseLength",
      integrationError = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_apigatewayv2_authorizer" "customers" {
  api_id           = aws_apigatewayv2_api.retail.id
  name             = "cognito-access-token"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    audience = [aws_cognito_user_pool_client.frontend.id]
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.customers.id}"
  }
}

resource "aws_apigatewayv2_integration" "service" {
  for_each               = local.services
  api_id                 = aws_apigatewayv2_api.retail.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_alias.live[each.key].invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

locals {
  api_routes = {
    "GET /api/products"             = { service = "products", private = false }
    "GET /api/products/{id}"        = { service = "products", private = false }
    "GET /api/orders"               = { service = "orders", private = true }
    "POST /api/orders"              = { service = "orders", private = true }
    "GET /api/orders/{id}"          = { service = "orders", private = true }
    "POST /api/support"             = { service = "support", private = true }
    "GET /api/support/tickets"      = { service = "support", private = true }
    "GET /api/support/tickets/{id}" = { service = "support", private = true }
  }
}

resource "aws_apigatewayv2_route" "retail" {
  for_each             = local.api_routes
  api_id               = aws_apigatewayv2_api.retail.id
  route_key            = each.key
  target               = "integrations/${aws_apigatewayv2_integration.service[each.value.service].id}"
  authorization_type   = each.value.private ? "JWT" : "NONE"
  authorizer_id        = each.value.private ? aws_apigatewayv2_authorizer.customers.id : null
  authorization_scopes = each.value.private ? ["openid"] : []
  # Scope enforcement rejects ID tokens; handlers additionally enforce ownership.
}

resource "aws_lambda_permission" "api" {
  for_each      = local.services
  statement_id  = "ApiGatewayInvokeLive"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.service[each.key].function_name
  qualifier     = aws_lambda_alias.live[each.key].name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.retail.execution_arn}/*/*"
}
