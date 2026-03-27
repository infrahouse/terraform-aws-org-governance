locals {
  module_version = "0.2.0"

  default_module_tags = {
    created_by_module = "infrahouse/org-governance/aws"
  }
}

data "aws_organizations_organization" "current" {}
