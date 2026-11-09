locals {
  lambda_trust = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  eni_statement = {
    Effect = "Allow"
    Action = [
      "ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeSubnets", "ec2:DeleteNetworkInterface",
      "ec2:AssignPrivateIpAddresses", "ec2:UnassignPrivateIpAddresses"
    ]
    # ENI lifecycle APIs used by the Lambda service require wildcard resources.
    Resource = "*"
  }
}

resource "aws_iam_role" "proxy" {
  name = "${local.name}-proxy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
      # Match the documented RDS Proxy trust policy. SourceArn/SourceAccount
      # conditions need service-context verification before adding them:
      # https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-iam-setup.html
    }]
  })
}

resource "aws_iam_role_policy" "proxy_secrets" {
  name = "read-only-database-secrets"
  role = aws_iam_role.proxy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = local.secret_arns
    }]
  })
}

resource "aws_iam_role" "lambda" {
  for_each           = local.services
  name               = "${local.name}-${each.key}"
  assume_role_policy = local.lambda_trust
}

resource "aws_iam_role_policy" "lambda" {
  for_each = local.services
  name     = "runtime"
  role     = aws_iam_role.lambda[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      local.eni_statement,
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.lambda[each.key].arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = "rds-db:connect"
        Resource = "arn:${local.partition}:rds-db:${var.aws_region}:${local.account_id}:dbuser:${local.proxy_id}/${local.app_user}"
      }
      ], each.key == "support" && local.bedrock_on ? [{
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = var.bedrock_model_arn
    }] : [])
  })
}

resource "aws_iam_role" "bootstrap" {
  count              = var.enable_bootstrap ? 1 : 0
  name               = "${local.name}-bootstrap"
  assume_role_policy = local.lambda_trust
}

resource "aws_iam_role_policy" "bootstrap" {
  count = var.enable_bootstrap ? 1 : 0
  name  = "temporary-database-initialization"
  role  = aws_iam_role.bootstrap[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.eni_statement,
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.bootstrap[0].arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = "rds-db:connect"
        Resource = "arn:${local.partition}:rds-db:${var.aws_region}:${local.account_id}:dbuser:${local.proxy_id}/${local.master_user}"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"]
        Resource = aws_secretsmanager_secret.application.arn
      },
      {
        Effect   = "Allow"
        Action   = "secretsmanager:GetRandomPassword"
        Resource = "*"
      }
    ]
  })
}
