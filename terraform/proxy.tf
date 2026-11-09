resource "aws_db_proxy" "retail" {
  name                   = "${local.name}-proxy"
  engine_family          = "POSTGRESQL"
  role_arn               = aws_iam_role.proxy.arn
  vpc_subnet_ids         = aws_subnet.application[*].id
  vpc_security_group_ids = [aws_security_group.proxy.id]
  require_tls            = true
  idle_client_timeout    = 300
  debug_logging          = false
  default_auth_scheme    = "NONE"

  dynamic "auth" {
    for_each = local.proxy_auth_secrets
    content {
      auth_scheme               = "SECRETS"
      secret_arn                = auth.value
      iam_auth                  = "REQUIRED"
      client_password_auth_type = "POSTGRES_SCRAM_SHA_256"
    }
  }
  depends_on = [aws_iam_role_policy.proxy_secrets]
}

resource "aws_db_proxy_default_target_group" "retail" {
  db_proxy_name = aws_db_proxy.retail.name
  connection_pool_config {
    connection_borrow_timeout    = 5
    max_connections_percent      = 70
    max_idle_connections_percent = 35
  }
}

resource "aws_db_proxy_target" "retail" {
  db_cluster_identifier = aws_rds_cluster.retail.id
  db_proxy_name         = aws_db_proxy.retail.name
  target_group_name     = aws_db_proxy_default_target_group.retail.name
  depends_on            = [aws_rds_cluster_instance.retail]
}
