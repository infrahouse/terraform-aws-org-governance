locals {
  module_version = "0.3.0"

  default_module_tags = {
    created_by_module = "infrahouse/org-governance/aws"
  }
}

data "aws_organizations_organization" "current" {}

data "aws_region" "current" {}
