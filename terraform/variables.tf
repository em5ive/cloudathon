variable "aws_region" {
  type        = string
  description = "Competition Region; the initial POC is intentionally Oregon only."
  default     = "us-west-2"
  validation {
    condition     = var.aws_region == "us-west-2"
    error_message = "The reviewed competition design uses us-west-2. Review the design before changing Regions."
  }
}

variable "project_name" {
  type        = string
  default     = "uh-retail-poc"
  description = "Distinct namespace, lowercase letters/numbers/hyphens, at most 24 characters."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,23}$", var.project_name))
    error_message = "Use 3-24 lowercase letters, numbers or hyphens, starting with a letter."
  }
}

variable "owner" {
  type        = string
  default     = "cloudathon-team"
  description = "Team ownership tag."
}

variable "expected_account_id" {
  type        = string
  description = "Competition AWS account ID, independently verified before planning."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Provide the verified 12-digit competition account ID."
  }
}

variable "aurora_engine_version" {
  type        = string
  description = "Exact Aurora PostgreSQL version verified as orderable with db.serverless and supported by RDS Proxy in us-west-2. No assumed version is deployed."
  validation {
    condition     = can(regex("^(16|17)\\.[0-9]+([.][0-9]+)?$", var.aurora_engine_version))
    error_message = "Use an explicitly verified Aurora PostgreSQL 16.x or 17.x version."
  }
}

variable "min_acu" {
  type        = number
  default     = 0.5
  description = "Minimum capacity PER instance. Proxy prevents useful scale-to-zero; retain a warm reader."
  validation {
    condition     = var.min_acu >= 0.5 && floor(var.min_acu * 2) == var.min_acu * 2
    error_message = "Use half-ACU steps of at least 0.5."
  }
}

variable "max_acu" {
  type        = number
  default     = 4
  description = "Maximum capacity PER Aurora instance."
  validation {
    condition     = var.max_acu >= var.min_acu && var.max_acu <= 16 && floor(var.max_acu * 2) == var.max_acu * 2
    error_message = "Use half-ACU steps between min_acu and 16; review costs for larger limits."
  }
}

variable "database_bootstrapped" {
  type        = bool
  default     = false
  description = "Set true only AFTER the separately approved bootstrap initializes the role, app secret, schema and seed."
}

variable "enable_bootstrap" {
  type        = bool
  default     = true
  description = "Temporary privileged bootstrap Lambda and proxy master auth. Remove with a reviewed plan after initialization."
  validation {
    condition     = var.enable_bootstrap || var.database_bootstrapped
    error_message = "At least bootstrap or initialized app authentication must remain enabled."
  }
}

variable "bedrock_model_id" {
  type        = string
  default     = ""
  description = "Verified in-Region Bedrock foundation model ID supporting Converse. Empty disables inference safely."
}

variable "bedrock_model_arn" {
  type        = string
  default     = ""
  description = "Exact us-west-2 foundation-model ARN corresponding to model ID; cross-Region inference profiles need a separate review."
  validation {
    condition = (var.bedrock_model_id == "" && var.bedrock_model_arn == "") || (
      var.bedrock_model_id != "" &&
      var.bedrock_model_arn == "arn:aws:bedrock:us-west-2::foundation-model/${var.bedrock_model_id}"
    )
    error_message = "Supply both a model ID and its exact regional foundation-model ARN, or leave both empty."
  }
}

variable "alarm_email" {
  type        = string
  default     = ""
  description = "Optional operations email. SNS confirmation is a separate user action after approved deployment."
}

variable "log_retention_days" {
  type        = number
  default     = 14
  description = "CloudWatch log retention. Logs contain request metadata, never JWTs or secret values."
  validation {
    condition     = contains([7, 14, 30, 60, 90], var.log_retention_days)
    error_message = "Choose 7, 14, 30, 60 or 90 days."
  }
}

variable "lambda_reserved_concurrency" {
  type = object({
    products = number
    orders   = number
    support  = number
  })
  default     = { products = 3, orders = 3, support = 2 }
  description = "Independent per-service reservations. Defaults reserve 8 runtime slots plus 1 temporary bootstrap slot; recheck current regional headroom before applying."
  validation {
    condition = alltrue([
      for reserved in values(var.lambda_reserved_concurrency) :
      reserved >= 1 && reserved <= 20 && floor(reserved) == reserved
    ])
    error_message = "Each service reservation must be a whole number between 1 and 20; larger reservations need a separate quota review."
  }
}

variable "lambda_live_versions" {
  type        = map(string)
  default     = {}
  description = "Pin each live alias to its reviewed published version before a subsequent code apply; empty is for initial deployment."
  validation {
    condition = alltrue([
      for service, version in var.lambda_live_versions :
      contains(["products", "orders", "support"], service) && can(regex("^[1-9][0-9]*$", version))
    ])
    error_message = "Use only products/orders/support and positive numeric published versions."
  }
}

variable "lambda_canary_versions" {
  type = map(object({
    version = string
    weight  = number
  }))
  default     = {}
  description = "Explicit candidate version and traffic fraction, applied only after a reviewed plan and release approval."
  validation {
    condition = alltrue([
      for service, candidate in var.lambda_canary_versions :
      contains(["products", "orders", "support"], service) &&
      can(regex("^[1-9][0-9]*$", candidate.version)) &&
      candidate.weight > 0 && candidate.weight < 1 &&
      contains(keys(var.lambda_live_versions), service) &&
      try(var.lambda_live_versions[service] != candidate.version, false)
    ])
    error_message = "Each canary needs a different explicitly pinned live version and a weight strictly between 0 and 1."
  }
}
