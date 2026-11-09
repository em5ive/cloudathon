output "cloudfront_url" {
  description = "Default AWS-managed CloudFront HTTPS frontend URL"
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}
output "api_url" {
  description = "Default API Gateway execute-api HTTPS base URL; routes start /api/"
  value       = aws_apigatewayv2_api.retail.api_endpoint
}
output "frontend_bucket" {
  description = "Private S3 origin bucket; public reads must return AccessDenied"
  value       = aws_s3_bucket.frontend.id
}
output "distribution_id" {
  value = aws_cloudfront_distribution.frontend.id
}
output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.customers.id
}
output "cognito_client_id" {
  value = aws_cognito_user_pool_client.frontend.id
}
output "cognito_login_domain" {
  value = "https://${aws_cognito_user_pool_domain.customers.domain}.auth.${var.aws_region}.amazoncognito.com"
}
output "bootstrap_function_name" {
  description = "Temporary privileged function; invoking it changes DB/secret contents and requires explicit approval"
  value       = var.enable_bootstrap ? aws_lambda_function.bootstrap[0].function_name : null
}
output "application_secret_arn" {
  description = "Reference only; secret values never pass through Terraform"
  value       = aws_secretsmanager_secret.application.arn
}
output "database_bootstrapped" {
  description = "Operator-declared readiness, not proof of successful database connectivity"
  value       = var.database_bootstrapped
}
output "database_proxy_endpoint" {
  description = "Private writer proxy endpoint; all app reads initially use writer, not the standby reader"
  value       = aws_db_proxy.retail.endpoint
}
output "database_cluster_identifier" {
  value = aws_rds_cluster.retail.id
}
output "lambda_aliases" {
  value = { for service, alias in aws_lambda_alias.live : service => { function_name = alias.function_name, alias = alias.name, version = alias.function_version } }
}
output "availability_zones" {
  value = local.azs
}
output "operations_topic_arn" {
  value = aws_sns_topic.operations.arn
}
