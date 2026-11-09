# OFFLINE CONFIGURATION TESTS ONLY. Every provider call is mocked, and every
# run uses command=plan. Fixture versions/identities are not verified AWS
# capabilities or a deployable competition-account plan.
mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:role/offline-test"
      user_id    = "OFFLINE_TEST"
    }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws", dns_suffix = "amazonaws.com" }
  }
  mock_data "aws_availability_zones" {
    defaults = {
      names    = ["us-west-2a", "us-west-2b"]
      zone_ids = ["usw2-az1", "usw2-az2"]
    }
  }
  mock_resource "aws_rds_cluster" {
    defaults = {
      id  = "offline-retail"
      arn = "arn:aws:rds:us-west-2:123456789012:cluster:offline-retail"
      master_user_secret = [{
        secret_arn    = "arn:aws:secretsmanager:us-west-2:123456789012:secret:offline-master-AbCdEf"
        secret_status = "active"
        kms_key_id    = "arn:aws:kms:us-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
      }]
    }
  }
  mock_resource "aws_db_proxy" {
    defaults = {
      arn      = "arn:aws:rds:us-west-2:123456789012:db-proxy:prx-OFFLINETEST"
      endpoint = "offline.proxy-abcdefghijkl.us-west-2.rds.amazonaws.com"
    }
  }
  mock_resource "aws_apigatewayv2_api" {
    defaults = {
      api_endpoint  = "https://offlinetest.execute-api.us-west-2.amazonaws.com"
      execution_arn = "arn:aws:execute-api:us-west-2:123456789012:offlinetest"
    }
  }
  mock_resource "aws_cloudfront_distribution" {
    defaults = {
      domain_name = "dofflinetest.cloudfront.net"
      arn         = "arn:aws:cloudfront::123456789012:distribution/EOFFLINETEST"
    }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:us-west-2:123456789012:secret:offline-app-AbCdEf" }
  }
  mock_resource "aws_lambda_function" {
    defaults = { version = "1" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:us-west-2:123456789012:log-group:offline-test" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:us-west-2:123456789012:offline-operations" }
  }
  mock_resource "aws_cloudwatch_event_rule" {
    defaults = { arn = "arn:aws:events:us-west-2:123456789012:rule/offline-database-events" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = {
      arn                         = "arn:aws:s3:::offline-frontend"
      bucket_regional_domain_name = "offline-frontend.s3.us-west-2.amazonaws.com"
    }
  }
  mock_resource "aws_cognito_user_pool" {
    defaults = { id = "us-west-2_OFFLINE123" }
  }
}

override_resource {
  target          = aws_subnet.application[0]
  override_during = plan
  values          = { id = "subnet-app-a" }
}
override_resource {
  target          = aws_subnet.application[1]
  override_during = plan
  values          = { id = "subnet-app-b" }
}
override_resource {
  target          = aws_subnet.database[0]
  override_during = plan
  values          = { id = "subnet-db-a" }
}
override_resource {
  target          = aws_subnet.database[1]
  override_during = plan
  values          = { id = "subnet-db-b" }
}
override_resource {
  target          = aws_security_group.lambda
  override_during = plan
  values          = { id = "sg-lambda" }
}
override_resource {
  target          = aws_security_group.proxy
  override_during = plan
  values          = { id = "sg-proxy" }
}
override_resource {
  target          = aws_security_group.database
  override_during = plan
  values          = { id = "sg-database" }
}

variables {
  expected_account_id   = "123456789012"
  aurora_engine_version = "16.6" # Test fixture only; never a deployment recommendation.
}

run "initial_bootstrap_security" {
  command = plan

  assert {
    condition = (
      length(aws_subnet.application) == 2 && length(aws_subnet.database) == 2 &&
      length(toset([for subnet in aws_subnet.application : subnet.availability_zone])) == 2 &&
      length(toset([for subnet in aws_subnet.database : subnet.availability_zone])) == 2 &&
      alltrue([for subnet in concat(aws_subnet.application, aws_subnet.database) : !subnet.map_public_ip_on_launch]) &&
      length(aws_route_table.application.route) == 0 && length(aws_route_table.database.route) == 0
    )
    error_message = "Application/database subnets must span two AZs without public IPs or internet routes."
  }
  assert {
    condition = (
      length(aws_rds_cluster_instance.retail) == 2 &&
      length(toset([for instance in aws_rds_cluster_instance.retail : instance.availability_zone])) == 2 &&
      alltrue([for instance in aws_rds_cluster_instance.retail : !instance.publicly_accessible && instance.instance_class == "db.serverless"]) &&
      toset(aws_db_subnet_group.retail.subnet_ids) == toset(aws_subnet.database[*].id) &&
      alltrue([for function in values(aws_lambda_function.service) :
        toset(function.vpc_config[0].subnet_ids) == toset(aws_subnet.application[*].id) &&
        toset(function.vpc_config[0].security_group_ids) == toset([aws_security_group.lambda.id])
      ])
    )
    error_message = "Lambda and Aurora must use their respective private two-AZ subnets; Aurora needs two serverless instances."
  }
  assert {
    condition = (
      aws_db_proxy.retail.require_tls &&
      alltrue([for auth in aws_db_proxy.retail.auth : auth.iam_auth == "REQUIRED"]) &&
      length([for parameter in aws_rds_cluster_parameter_group.retail.parameter : parameter if parameter.name == "rds.force_ssl" && parameter.value == "1"]) == 1 &&
      aws_vpc_security_group_ingress_rule.database_proxy.referenced_security_group_id == aws_security_group.proxy.id &&
      aws_vpc_security_group_ingress_rule.proxy_lambda.referenced_security_group_id == aws_security_group.lambda.id &&
      aws_vpc_security_group_ingress_rule.database_proxy.from_port == 5432 &&
      aws_vpc_security_group_ingress_rule.proxy_lambda.from_port == 5432
    )
    error_message = "Enforce TLS on both database hops and restrict PostgreSQL ingress to the preceding tier."
  }
  assert {
    condition = (
      aws_rds_cluster.retail.storage_encrypted &&
      aws_rds_cluster.retail.deletion_protection && !aws_rds_cluster.retail.skip_final_snapshot &&
      aws_rds_cluster.retail.backup_retention_period >= 7 &&
      aws_rds_cluster.retail.manage_master_user_password &&
      aws_rds_cluster.retail.master_password == null &&
      alltrue([for function in values(aws_lambda_function.service) :
        function.environment[0].variables.DB_USER == "retail_app" &&
        function.environment[0].variables.DB_AUTH == "iam" &&
        !contains(keys(function.environment[0].variables), "DB_PASSWORD") &&
        !contains(keys(function.environment[0].variables), "APP_SECRET_ARN")
      ]) &&
      length([for parameter in aws_rds_cluster_parameter_group.retail.parameter : parameter if
        parameter.name == "log_parameter_max_length" && parameter.value == "0"
      ]) == 1
    )
    error_message = "Protect persistent data, avoid raw credentials, and prevent parameter values entering database logs."
  }
  assert {
    condition = (
      aws_cloudfront_distribution.frontend.viewer_certificate[0].cloudfront_default_certificate &&
      aws_cloudfront_distribution.frontend.viewer_certificate[0].acm_certificate_arn == null &&
      try(length(aws_cloudfront_distribution.frontend.aliases), 0) == 0 &&
      aws_cloudfront_distribution.frontend.default_cache_behavior[0].viewer_protocol_policy == "redirect-to-https" &&
      aws_cloudfront_origin_access_control.frontend.signing_behavior == "always" &&
      aws_cloudfront_origin_access_control.frontend.signing_protocol == "sigv4" &&
      aws_s3_bucket_public_access_block.frontend.block_public_acls &&
      aws_s3_bucket_public_access_block.frontend.block_public_policy &&
      aws_s3_bucket_public_access_block.frontend.ignore_public_acls &&
      aws_s3_bucket_public_access_block.frontend.restrict_public_buckets &&
      jsondecode(aws_s3_bucket_policy.frontend.policy).Statement[0].Condition.StringEquals["AWS:SourceArn"] == aws_cloudfront_distribution.frontend.arn
    )
    error_message = "Use private S3 with signed OAC and default CloudFront HTTPS without a custom domain/certificate."
  }
  assert {
    condition = (
      length(aws_cloudfront_distribution.frontend.origin) == 1 &&
      !aws_apigatewayv2_api.retail.disable_execute_api_endpoint &&
      startswith(output.api_url, "https://") &&
      endswith(output.cloudfront_url, ".cloudfront.net") &&
      aws_apigatewayv2_api.retail.cors_configuration[0].allow_origins == toset([output.cloudfront_url]) &&
      contains(aws_apigatewayv2_api.retail.cors_configuration[0].allow_headers, "authorization") &&
      alltrue([for key, route in aws_apigatewayv2_route.retail :
        startswith(key, "GET /api/products") ? route.authorization_type == "NONE" :
        route.authorization_type == "JWT" && contains(route.authorization_scopes, "openid")
      ])
    )
    error_message = "Use direct HTTPS execute-api with exact-origin CORS and JWT access-token scopes on all private routes."
  }
  assert {
    condition = (
      length(aws_lambda_function.bootstrap) == 1 &&
      length(aws_db_proxy.retail.auth) == 1 &&
      one(aws_db_proxy.retail.auth).secret_arn == aws_rds_cluster.retail.master_user_secret[0].secret_arn &&
      aws_lambda_function.bootstrap[0].environment[0].variables.DB_USER == "retail_admin" &&
      length(aws_vpc_endpoint.bedrock_runtime) == 0 &&
      length(aws_vpc_endpoint.secretsmanager) == 1 &&
      length(aws_cloudwatch_log_metric_filter.application_failures) == 3 &&
      length(aws_cloudwatch_metric_alarm.application_failures) == 3
    )
    error_message = "Initial bootstrap is explicit and isolated; disabled Bedrock must not add an endpoint, and handled app failures need alarms."
  }
}

run "sns_topic_policy_supported_actions" {
  command = plan

  assert {
    condition = toset(one([
      for statement in jsondecode(aws_sns_topic_policy.operations.policy).Statement : statement
      if statement.Sid == "AccountOwner"
      ]).Action) == toset([
      "SNS:GetTopicAttributes", "SNS:SetTopicAttributes", "SNS:AddPermission",
      "SNS:RemovePermission", "SNS:DeleteTopic", "SNS:Subscribe",
      "SNS:ListSubscriptionsByTopic", "SNS:Publish"
    ])
    error_message = "SNS topic policies must enumerate supported topic-scoped owner actions."
  }
  assert {
    condition = toset([
      for statement in jsondecode(aws_sns_topic_policy.operations.policy).Statement : statement.Sid
      ]) == toset(["AccountOwner", "CloudWatchAlarms", "RDSFailoverEvents"]) && alltrue([
      for statement in jsondecode(aws_sns_topic_policy.operations.policy).Statement :
      statement.Action == "SNS:Publish" &&
      statement.Principal.Service == "cloudwatch.amazonaws.com" &&
      statement.Condition.StringEquals["aws:SourceAccount"] == "123456789012"
      if statement.Sid == "CloudWatchAlarms"
      ]) && alltrue([
      for statement in jsondecode(aws_sns_topic_policy.operations.policy).Statement :
      statement.Action == "SNS:Publish" &&
      statement.Principal.Service == "events.amazonaws.com" &&
      statement.Condition.ArnEquals["aws:SourceArn"] == aws_cloudwatch_event_rule.database.arn
      if statement.Sid == "RDSFailoverEvents"
    ])
    error_message = "The existing CloudWatch and EventBridge publish permissions must remain scoped and intact."
  }
}

run "initialized_application_security" {
  command = plan
  variables {
    database_bootstrapped = true
    enable_bootstrap      = false
    lambda_live_versions  = { products = "1", orders = "1", support = "1" }
    lambda_canary_versions = {
      support = { version = "2", weight = 0.10 }
    }
  }
  assert {
    condition = (
      length(aws_lambda_function.bootstrap) == 0 &&
      length(aws_vpc_endpoint.secretsmanager) == 0 &&
      length(aws_iam_role.bootstrap) == 0 &&
      length(aws_db_proxy.retail.auth) == 1 &&
      one(aws_db_proxy.retail.auth).secret_arn == aws_secretsmanager_secret.application.arn &&
      length(jsondecode(aws_iam_role_policy.proxy_secrets.policy).Statement[0].Resource) == 1 &&
      one(jsondecode(aws_iam_role_policy.proxy_secrets.policy).Statement[0].Resource) == aws_secretsmanager_secret.application.arn
    )
    error_message = "Initialized mode must remove bootstrap/master proxy credentials and keep only the least-privilege app secret."
  }
  assert {
    condition = alltrue([for policy in values(aws_iam_role_policy.lambda) :
      one([for statement in jsondecode(policy.policy).Statement : statement if try(statement.Action == "rds-db:connect", false)]).Resource == "arn:aws:rds-db:us-west-2:123456789012:dbuser:prx-OFFLINETEST/retail_app"
    ])
    error_message = "Every normal function must connect only as retail_app on this exact proxy resource."
  }
  assert {
    condition = (
      aws_lambda_alias.live["support"].function_version == "1" &&
      aws_lambda_alias.live["support"].routing_config[0].additional_version_weights == tomap({ "2" = 0.10 }) &&
      length(aws_lambda_alias.live["products"].routing_config) == 0 &&
      length(aws_lambda_alias.live["orders"].routing_config) == 0 &&
      alltrue([for permission in values(aws_lambda_permission.api) : permission.qualifier == "live"])
    )
    error_message = "A Support canary must preserve live versions for Products/Orders and API Gateway must invoke stable aliases."
  }
}

run "reject_uninitialized_without_bootstrap" {
  command = plan
  variables {
    database_bootstrapped = false
    enable_bootstrap      = false
  }
  expect_failures = [var.enable_bootstrap]
}

run "reject_wrong_account" {
  command = plan
  variables {
    expected_account_id = "999999999999"
  }
  expect_failures = [aws_vpc.retail]
}
