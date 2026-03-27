locals {
  module_version = "0.1.0"

  default_module_tags = {
    created_by_module = "infrahouse/org-governance/aws"
  }
}

data "aws_organizations_organization" "current" {}
