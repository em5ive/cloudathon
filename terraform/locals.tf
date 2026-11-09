locals {
  name        = var.project_name
  account_id  = data.aws_caller_identity.current.account_id
  partition   = data.aws_partition.current.partition
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)
  db_name     = "retail"
  app_user    = "retail_app"
  master_user = "retail_admin"
  bedrock_on  = var.bedrock_model_id != ""
  # The auth block identities depend only on reviewed input flags. Secret ARN
  # VALUES remain computed until creation; never use them as for_each set keys.
  proxy_auth_secrets = merge(
    var.enable_bootstrap ? { bootstrap = aws_rds_cluster.retail.master_user_secret[0].secret_arn } : {},
    var.database_bootstrapped ? { runtime = aws_secretsmanager_secret.application.arn } : {}
  )
  secret_arns = values(local.proxy_auth_secrets)
  proxy_id    = element(split(":", aws_db_proxy.retail.arn), 6)
  services = {
    products = { memory = 256, timeout = 12, concurrency = var.lambda_reserved_concurrency.products }
    orders   = { memory = 256, timeout = 15, concurrency = var.lambda_reserved_concurrency.orders }
    support  = { memory = 512, timeout = 25, concurrency = var.lambda_reserved_concurrency.support }
  }
  lambda_env = {
    DB_HOST = aws_db_proxy.retail.endpoint
    DB_NAME = local.db_name
    DB_USER = local.app_user
    DB_AUTH = "iam"
  }
  site_files = { for path in fileset("${path.module}/../frontend", "**") : path => path if !contains(["config.json", "config.example.json"], path) && !startswith(path, ".") }
  mime_types = { html = "text/html; charset=utf-8", css = "text/css; charset=utf-8", js = "text/javascript; charset=utf-8", json = "application/json", svg = "image/svg+xml", png = "image/png", ico = "image/x-icon" }
}
