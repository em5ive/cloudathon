resource "aws_security_group" "lambda" {
  name_prefix = "${local.name}-lambda-"
  description = "Private Lambda; no inbound rules"
  vpc_id      = aws_vpc.retail.id
}
resource "aws_security_group" "proxy" {
  name_prefix = "${local.name}-proxy-"
  description = "Only Lambda PostgreSQL access"
  vpc_id      = aws_vpc.retail.id
}
resource "aws_security_group" "database" {
  name_prefix = "${local.name}-db-"
  description = "Only RDS Proxy PostgreSQL access"
  vpc_id      = aws_vpc.retail.id
}
resource "aws_security_group" "endpoints" {
  name_prefix = "${local.name}-endpoints-"
  description = "Only Lambda HTTPS access to private AWS endpoints"
  vpc_id      = aws_vpc.retail.id
}

resource "aws_vpc_security_group_egress_rule" "lambda_proxy" {
  security_group_id            = aws_security_group.lambda.id
  referenced_security_group_id = aws_security_group.proxy.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_ingress_rule" "proxy_lambda" {
  security_group_id            = aws_security_group.proxy.id
  referenced_security_group_id = aws_security_group.lambda.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_egress_rule" "proxy_database" {
  security_group_id            = aws_security_group.proxy.id
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_ingress_rule" "database_proxy" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.proxy.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_egress_rule" "lambda_endpoints" {
  security_group_id            = aws_security_group.lambda.id
  referenced_security_group_id = aws_security_group.endpoints.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
resource "aws_vpc_security_group_ingress_rule" "endpoints_lambda" {
  security_group_id            = aws_security_group.endpoints.id
  referenced_security_group_id = aws_security_group.lambda.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
