variable "region" {
  type    = string
  default = "us-west-2"
}

variable "role_arn" {
  type    = string
  default = null
}

provider "aws" {
  region = var.region

  dynamic "assume_role" {
    for_each = var.role_arn != null ? [var.role_arn] : []
    content {
      role_arn = assume_role.value
    }
  }

  default_tags {
    tags = {
      created_by = "infrahouse/terraform-aws-org-governance"
    }
  }
}
