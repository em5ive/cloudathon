resource "aws_sns_topic" "operations" {
  name = "${local.name}-operations"
}

resource "aws_sns_topic_subscription" "operations" {
  count     = var.alarm_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.operations.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_sns_topic_policy" "operations" {
  arn = aws_sns_topic.operations.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountOwner"
        Effect    = "Allow"
        Principal = { AWS = "arn:${local.partition}:iam::${local.account_id}:root" }
        # SNS topic resource policies accept topic-scoped actions, rather
        # than every action in the SNS service namespace.
        Action = [
          "SNS:GetTopicAttributes",
          "SNS:SetTopicAttributes",
          "SNS:AddPermission",
          "SNS:RemovePermission",
          "SNS:DeleteTopic",
          "SNS:Subscribe",
          "SNS:ListSubscriptionsByTopic",
          "SNS:Publish"
        ]
        Resource = aws_sns_topic.operations.arn
      },
      {
        Sid       = "CloudWatchAlarms"
        Effect    = "Allow"
        Principal = { Service = "cloudwatch.amazonaws.com" }
        Action    = "SNS:Publish"
        Resource  = aws_sns_topic.operations.arn
        Condition = {
          StringEquals = { "aws:SourceAccount" = local.account_id }
          ArnLike      = { "aws:SourceArn" = "arn:${local.partition}:cloudwatch:${var.aws_region}:${local.account_id}:alarm:${local.name}-*" }
        }
      },
      {
        Sid       = "RDSFailoverEvents"
        Effect    = "Allow"
        Principal = { Service = "events.amazonaws.com" }
        Action    = "SNS:Publish"
        Resource  = aws_sns_topic.operations.arn
        Condition = { ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.database.arn } }
      }
    ]
  })
}

locals {
  service_alarms = merge([
    for service, config in local.services : {
      "${service}-errors"    = { service = service, metric = "Errors", statistic = "Sum", threshold = 1, description = "Inspect function logs and alias release; distinguish validation 4xx from unexpected failures." }
      "${service}-throttles" = { service = service, metric = "Throttles", statistic = "Sum", threshold = 1, description = "Check API traffic and concurrency quotas; increase only after DB and cost review." }
      "${service}-duration"  = { service = service, metric = "Duration", statistic = "Maximum", threshold = config.timeout * 800, description = "Inspect DB borrow latency and downstream latency before increasing timeouts." }
    }
  ]...)
}

resource "aws_cloudwatch_metric_alarm" "lambda" {
  for_each            = local.service_alarms
  alarm_name          = "${local.name}-${each.key}"
  alarm_description   = each.value.description
  namespace           = "AWS/Lambda"
  metric_name         = each.value.metric
  statistic           = each.value.statistic
  period              = 60
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = each.value.threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = aws_lambda_function.service[each.value.service].function_name }
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]
}

# Handlers deliberately translate unexpected exceptions to HTTP 503. Those
# handled failures do not increment Lambda Errors, so monitor the safe log event.
resource "aws_cloudwatch_log_metric_filter" "application_failures" {
  for_each       = local.services
  name           = "${local.name}-${each.key}-request-failures"
  log_group_name = aws_cloudwatch_log_group.lambda[each.key].name
  pattern        = "\"request_failed\""
  metric_transformation {
    name          = "${title(each.key)}RequestFailures"
    namespace     = "Cloudathon/Retail"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "application_failures" {
  for_each            = local.services
  alarm_name          = "${local.name}-${each.key}-request-failures"
  alarm_description   = "Handler returned HTTP 503 after a caught exception. Inspect redacted request_failed events, DB connectivity and release version."
  namespace           = "Cloudathon/Retail"
  metric_name         = "${title(each.key)}RequestFailures"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
}

resource "aws_cloudwatch_metric_alarm" "api_errors" {
  alarm_name          = "${local.name}-api-5xx"
  alarm_description   = "Inspect API access log request IDs, Lambda errors and RDS availability."
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { ApiId = aws_apigatewayv2_api.retail.id, Stage = aws_apigatewayv2_stage.live.name }
  alarm_actions       = [aws_sns_topic.operations.arn]
}

resource "aws_cloudwatch_metric_alarm" "database_capacity" {
  count               = 2
  alarm_name          = "${local.name}-database-${count.index + 1}-capacity"
  alarm_description   = "Capacity near configured maximum; inspect query latency and workload before raising ACU ceiling."
  namespace           = "AWS/RDS"
  metric_name         = "ACUUtilization"
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 5
  threshold           = 80
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "missing"
  dimensions          = { DBInstanceIdentifier = aws_rds_cluster_instance.retail[count.index].id }
  alarm_actions       = [aws_sns_topic.operations.arn]
}

resource "aws_cloudwatch_metric_alarm" "proxy_borrow_latency" {
  alarm_name          = "${local.name}-proxy-borrow-latency"
  alarm_description   = "Borrow latency over 500ms; inspect connection saturation, pinned sessions and DB failover."
  namespace           = "AWS/RDS"
  metric_name         = "DatabaseConnectionsBorrowLatency"
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 3
  threshold           = 500000
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { ProxyName = aws_db_proxy.retail.name }
  alarm_actions       = [aws_sns_topic.operations.arn]
}

resource "aws_cloudwatch_metric_alarm" "proxy_utilization" {
  alarm_name          = "${local.name}-proxy-connection-utilization"
  alarm_description   = "Borrowed connections exceed 80% of proxy allowed capacity; inspect long transactions and pinning."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  threshold           = 80
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  metric_query {
    id          = "utilization"
    expression  = "IF(allowed>0,100*borrowed/allowed,0)"
    label       = "Proxy borrowed connection percentage"
    return_data = true
  }
  metric_query {
    id = "borrowed"
    metric {
      namespace   = "AWS/RDS"
      metric_name = "DatabaseConnectionsCurrentlyBorrowed"
      dimensions  = { ProxyName = aws_db_proxy.retail.name }
      period      = 60
      stat        = "Sum"
    }
  }
  metric_query {
    id = "allowed"
    metric {
      namespace   = "AWS/RDS"
      metric_name = "MaxDatabaseConnectionsAllowed"
      dimensions  = { ProxyName = aws_db_proxy.retail.name }
      period      = 60
      stat        = "Sum"
    }
  }
}

resource "aws_cloudwatch_log_metric_filter" "bedrock_fallback" {
  name           = "${local.name}-bedrock-fallback"
  log_group_name = aws_cloudwatch_log_group.lambda["support"].name
  pattern        = "\"bedrock_fallback\""
  metric_transformation {
    name          = "BedrockFallback"
    namespace     = "Cloudathon/Retail"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "bedrock_fallback" {
  alarm_name          = "${local.name}-bedrock-fallback"
  alarm_description   = "Support is serving deterministic fallback. Inspect model permissions, endpoint and invocation errors; core retail remains available."
  namespace           = "Cloudathon/Retail"
  metric_name         = "BedrockFallback"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
}

resource "aws_cloudwatch_event_rule" "database" {
  name        = "${local.name}-database-events"
  description = "Notify operations of Aurora failover and failure events"
  event_pattern = jsonencode({
    source        = ["aws.rds"]
    "detail-type" = ["RDS DB Cluster Event"]
    resources     = [aws_rds_cluster.retail.arn]
    detail        = { EventCategories = ["failover", "failure"] }
  })
}
resource "aws_cloudwatch_event_target" "database" {
  rule = aws_cloudwatch_event_rule.database.name
  arn  = aws_sns_topic.operations.arn
}

resource "aws_cloudwatch_dashboard" "retail" {
  dashboard_name = "${local.name}-operations"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6,
        properties = {
          title   = "Independent Lambda invocations", region = var.aws_region, stat = "Sum", period = 60,
          metrics = [for service in keys(local.services) : ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.service[service].function_name]]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6,
        properties = {
          title   = "Aurora capacity per instance", region = var.aws_region, stat = "Average", period = 60,
          metrics = [for instance in aws_rds_cluster_instance.retail : ["AWS/RDS", "ServerlessDatabaseCapacity", "DBInstanceIdentifier", instance.id]]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6,
        properties = {
          title = "Proxy connections", region = var.aws_region, stat = "Sum", period = 60,
          metrics = [
            ["AWS/RDS", "ClientConnections", "ProxyName", aws_db_proxy.retail.name],
            ["AWS/RDS", "DatabaseConnections", "ProxyName", aws_db_proxy.retail.name],
            ["AWS/RDS", "DatabaseConnectionsCurrentlySessionPinned", "ProxyName", aws_db_proxy.retail.name]
          ]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6,
        properties = {
          title = "API errors and support fallback", region = var.aws_region, stat = "Sum", period = 60,
          metrics = [
            ["AWS/ApiGateway", "5xx", "ApiId", aws_apigatewayv2_api.retail.id, "Stage", "$default"],
            ["Cloudathon/Retail", "BedrockFallback"]
          ]
        }
      }
    ]
  })
}
