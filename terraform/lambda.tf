resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.services
  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "service" {
  for_each                       = local.services
  function_name                  = "${local.name}-${each.key}"
  description                    = "Retail ${each.key}; private VPC, verified TLS, IAM to RDS Proxy"
  role                           = aws_iam_role.lambda[each.key].arn
  runtime                        = "python3.13"
  architectures                  = ["x86_64"]
  handler                        = "${each.key}.handler.handler"
  filename                       = "${path.module}/../artifacts/${each.key}.zip"
  source_code_hash               = filebase64sha256("${path.module}/../artifacts/${each.key}.zip")
  memory_size                    = each.value.memory
  timeout                        = each.value.timeout
  reserved_concurrent_executions = each.value.concurrency
  publish                        = true

  vpc_config {
    subnet_ids         = aws_subnet.application[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }
  environment {
    variables = merge(local.lambda_env, each.key == "support" ? { BEDROCK_MODEL_ID = var.bedrock_model_id } : {})
  }
  logging_config {
    log_format = "JSON"
  }
  depends_on = [
    aws_iam_role_policy.lambda,
    aws_db_proxy_target.retail,
    aws_vpc_security_group_egress_rule.lambda_proxy,
    aws_vpc_security_group_ingress_rule.proxy_lambda,
    aws_vpc_security_group_egress_rule.lambda_endpoints,
    aws_vpc_security_group_ingress_rule.endpoints_lambda,
    aws_vpc_endpoint.secretsmanager
  ]
}

resource "aws_lambda_alias" "live" {
  for_each         = local.services
  name             = "live"
  description      = "Stable application alias; reviewed version changes are independent per function"
  function_name    = aws_lambda_function.service[each.key].function_name
  function_version = lookup(var.lambda_live_versions, each.key, aws_lambda_function.service[each.key].version)
  dynamic "routing_config" {
    for_each = contains(keys(var.lambda_canary_versions), each.key) ? [var.lambda_canary_versions[each.key]] : []
    content {
      additional_version_weights = { (routing_config.value.version) = routing_config.value.weight }
    }
  }
}

resource "aws_cloudwatch_log_group" "bootstrap" {
  count             = var.enable_bootstrap ? 1 : 0
  name              = "/aws/lambda/${local.name}-bootstrap"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "bootstrap" {
  count                          = var.enable_bootstrap ? 1 : 0
  function_name                  = "${local.name}-bootstrap"
  description                    = "Temporary privileged initialization; invocation requires separate explicit approval"
  role                           = aws_iam_role.bootstrap[0].arn
  runtime                        = "python3.13"
  architectures                  = ["x86_64"]
  handler                        = "bootstrap.handler.handler"
  filename                       = "${path.module}/../artifacts/bootstrap.zip"
  source_code_hash               = filebase64sha256("${path.module}/../artifacts/bootstrap.zip")
  memory_size                    = 256
  timeout                        = 60
  reserved_concurrent_executions = 1
  publish                        = true
  vpc_config {
    subnet_ids         = aws_subnet.application[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }
  environment {
    variables = merge(local.lambda_env, {
      DB_USER        = local.master_user
      APP_DB_USER    = local.app_user
      APP_SECRET_ARN = aws_secretsmanager_secret.application.arn
    })
  }
  logging_config {
    log_format = "JSON"
  }
  depends_on = [
    aws_iam_role_policy.bootstrap,
    aws_db_proxy_target.retail,
    aws_vpc_endpoint.secretsmanager,
    aws_vpc_security_group_egress_rule.lambda_proxy,
    aws_vpc_security_group_ingress_rule.proxy_lambda,
    aws_vpc_security_group_egress_rule.proxy_database,
    aws_vpc_security_group_ingress_rule.database_proxy,
    aws_vpc_security_group_egress_rule.lambda_endpoints,
    aws_vpc_security_group_ingress_rule.endpoints_lambda
  ]
}
