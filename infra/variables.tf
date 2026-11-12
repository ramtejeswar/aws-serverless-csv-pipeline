variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short name that prefixes every resource."
  type        = string
  default     = "csv-pipeline"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,24}$", var.project_name))
    error_message = "Use 3-24 lowercase letters, digits or hyphens."
  }
}

variable "environment" {
  description = "Deployment environment (dev, prod, ...). Part of every resource name, so environments never collide."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z0-9]{2,10}$", var.environment))
    error_message = "Use 2-10 lowercase letters or digits."
  }
}

variable "alert_email" {
  description = "Email address that receives alarm notifications. Leave empty to create the alarms without a subscriber."
  type        = string
  default     = ""
}

variable "data_retention_days" {
  description = "Days before uploaded files (S3 lifecycle) and stored jobs and records (DynamoDB TTL) are deleted."
  type        = number
  default     = 7

  validation {
    condition     = var.data_retention_days >= 1 && var.data_retention_days <= 365
    error_message = "Must be between 1 and 365."
  }
}

variable "max_receive_count" {
  description = "How many times a message is attempted before SQS moves it to the dead-letter queue."
  type        = number
  default     = 3
}

variable "lambda_runtime" {
  description = "Python runtime for every function."
  type        = string
  default     = "python3.13"
}

variable "lambda_architecture" {
  description = "arm64 (Graviton) costs less per GB-second than x86_64 and runs pure-Python code unchanged."
  type        = string
  default     = "arm64"

  validation {
    condition     = contains(["arm64", "x86_64"], var.lambda_architecture)
    error_message = "Must be arm64 or x86_64."
  }
}

variable "log_level" {
  description = "Application log level Lambda lets through (Lambda's names, e.g. WARN not WARNING)."
  type        = string
  default     = "INFO"

  validation {
    condition     = contains(["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"], var.log_level)
    error_message = "Must be one of TRACE, DEBUG, INFO, WARN, ERROR, FATAL."
  }
}

variable "log_retention_days" {
  description = "How long CloudWatch keeps logs. Without this, logs are kept (and billed) forever."
  type        = number
  default     = 7

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365], var.log_retention_days)
    error_message = "Must be a retention period CloudWatch supports, e.g. 1, 3, 7, 14, 30, 90 or 365."
  }
}

variable "throttle_rate_limit" {
  description = "Steady-state requests per second allowed across the whole API."
  type        = number
  default     = 10
}

variable "throttle_burst_limit" {
  description = "Short burst of requests allowed above the steady rate."
  type        = number
  default     = 20
}
