terraform {
  required_version = ">= 1.11.0, < 2.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
  # Intentionally no shared backend. Review and approve an encrypted S3 backend
  # with use_lockfile=true before any team deployment; never migrate old state.
}
