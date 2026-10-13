terraform {
  required_version = ">= 1.13.5, < 2.0.0"
  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Moto 5.2.4 implements PutBucketTagging, but not tags on CreateBucket.
      # Pin the provider that uses the supported API; retain ownership verification.
      version = "= 5.100.0"
    }
  }
}

variable "endpoint" {
  type    = string
  default = "http://127.0.0.1:5000"
  validation {
    condition     = can(regex("^http://(127\\.0\\.0\\.1|localhost|moto):[0-9]+$", var.endpoint))
    error_message = "This free edition only targets a local Moto endpoint."
  }
}
variable "request_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.request_id))
    error_message = "A 32-character hexadecimal request identifier is required."
  }
}
variable "slug" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,29}$", var.slug))
    error_message = "Use a lowercase sandbox name of 3-30 characters."
  }
}
variable "owner" { type = string }

provider "aws" {
  region                      = "us-east-1"
  access_key                  = "testing"
  secret_key                  = "testing"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  skip_region_validation      = true
  s3_use_path_style           = true
  endpoints {
    s3  = var.endpoint
    iam = var.endpoint
    sts = var.endpoint
  }
}

locals {
  bucket = "cd-${var.slug}-${substr(var.request_id, 0, 12)}"
  role   = "cd-${var.request_id}"
  tags   = { CloudDeskRequest = var.request_id, Owner = var.owner }
}

resource "aws_s3_bucket" "sandbox" {
  bucket        = local.bucket
  force_destroy = true
  tags          = local.tags
}
resource "aws_s3_bucket_public_access_block" "sandbox" {
  bucket                  = aws_s3_bucket.sandbox.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "sandbox" {
  bucket = aws_s3_bucket.sandbox.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_iam_role" "sandbox" {
  name = local.role
  tags = local.tags
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRole"
      Principal = { AWS = "arn:aws:iam::123456789012:root" }
    }]
  })
}
resource "aws_iam_role_policy" "sandbox" {
  name = "sandbox-access"
  role = aws_iam_role.sandbox.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.sandbox.arn },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "${aws_s3_bucket.sandbox.arn}/*" }
    ]
  })
}

output "bucket" { value = aws_s3_bucket.sandbox.id }
output "role" { value = aws_iam_role.sandbox.name }
