# All calls are mocked. Unlike safety.tftest.hcl, resource computed attributes
# stay unknown during PLAN. This exercises the first-deployment ARN problem.
mock_provider "aws" {
  override_during = apply
  mock_data "aws_caller_identity" {
    override_during = plan
    defaults = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:role/offline-test"
      user_id    = "OFFLINE_TEST"
    }
  }
  mock_data "aws_partition" {
    override_during = plan
    defaults        = { partition = "aws", dns_suffix = "amazonaws.com" }
  }
  mock_data "aws_availability_zones" {
    override_during = plan
    defaults = {
      names    = ["us-west-2a", "us-west-2b"]
      zone_ids = ["usw2-az1", "usw2-az2"]
    }
  }
}

variables {
  expected_account_id   = "123456789012"
  aurora_engine_version = "16.6" # Offline fixture only.
}

run "computed_bootstrap_arn" {
  command = plan
  assert {
    condition     = toset(keys(local.proxy_auth_secrets)) == toset(["bootstrap"]) && length(local.secret_arns) == 1
    error_message = "Bootstrap auth must have a stable key before the master secret ARN is known."
  }
  assert {
    condition     = aws_db_proxy.retail.require_tls && one(aws_db_proxy.retail.auth).iam_auth == "REQUIRED" && one(aws_db_proxy.retail.auth).client_password_auth_type == "POSTGRES_SCRAM_SHA_256"
    error_message = "Computed ARNs must not weaken TLS, IAM or SCRAM authentication."
  }
  assert {
    condition     = sum([for service in values(aws_lambda_function.service) : service.reserved_concurrent_executions]) + aws_lambda_function.bootstrap[0].reserved_concurrent_executions == 9
    error_message = "Default initial deployment must reserve eight independent runtime slots plus one bootstrap slot."
  }
}

run "computed_overlap_arns" {
  command = plan
  variables {
    enable_bootstrap      = true
    database_bootstrapped = true
  }
  assert {
    condition     = toset(keys(local.proxy_auth_secrets)) == toset(["bootstrap", "runtime"]) && length(local.secret_arns) == 2
    error_message = "An explicitly reviewed overlap phase needs two stable credential identities."
  }
}

run "computed_runtime_arn" {
  command = plan
  variables {
    enable_bootstrap      = false
    database_bootstrapped = true
  }
  assert {
    condition     = toset(keys(local.proxy_auth_secrets)) == toset(["runtime"]) && length(local.secret_arns) == 1 && length(aws_lambda_function.bootstrap) == 0
    error_message = "Initialized auth must retain only the runtime key and remove bootstrap access."
  }
}
