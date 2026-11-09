resource "aws_cognito_user_pool" "customers" {
  name                     = "${local.name}-customers"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  deletion_protection      = "ACTIVE"
  mfa_configuration        = "OFF"
  user_pool_tier           = "LITE"

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 1
  }
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
  }
}

resource "aws_cognito_user_pool_domain" "customers" {
  domain       = "${local.name}-${local.account_id}-${var.aws_region}"
  user_pool_id = aws_cognito_user_pool.customers.id
  # AWS-hosted domain, no custom domain and no ACM certificate.
}

resource "aws_cognito_user_pool_client" "frontend" {
  name                                 = "${local.name}-browser"
  user_pool_id                         = aws_cognito_user_pool.customers.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["https://${aws_cloudfront_distribution.frontend.domain_name}/"]
  logout_urls                          = ["https://${aws_cloudfront_distribution.frontend.domain_name}/"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  access_token_validity                = 15
  id_token_validity                    = 15
  refresh_token_validity               = 1
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH"]
  read_attributes                      = ["email", "email_verified", "sub"]
  write_attributes                     = ["email"]
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}
