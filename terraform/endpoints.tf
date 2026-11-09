resource "aws_vpc_endpoint" "secretsmanager" {
  count               = var.enable_bootstrap ? 1 : 0
  vpc_id              = aws_vpc.retail.id
  service_name        = "com.amazonaws.${var.aws_region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.application[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = "*"
      Action    = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue", "secretsmanager:GetRandomPassword"]
      Resource  = "*"
      Condition = { StringEquals = { "aws:PrincipalAccount" = local.account_id } }
    }]
  })
  tags = { Name = "${local.name}-secretsmanager" }
}

resource "aws_vpc_endpoint" "bedrock_runtime" {
  count               = local.bedrock_on ? 1 : 0
  vpc_id              = aws_vpc.retail.id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.application[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = "*"
      Action    = "bedrock:InvokeModel"
      Resource  = var.bedrock_model_arn
      Condition = { ArnEquals = { "aws:PrincipalArn" = aws_iam_role.lambda["support"].arn } }
    }]
  })
  tags = { Name = "${local.name}-bedrock-runtime" }
}
