# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## First Steps

**Your first tool call in this repository MUST be reading .claude/CODING_STANDARD.md.
Do not read any other files, search, or take any actions until you have read it.**
This contains InfraHouse's comprehensive coding standards for Terraform, Python, and general formatting rules.

## Repository Overview

This is an InfraHouse Terraform module (`terraform-aws-org-governance`) for AWS organization governance. It follows the InfraHouse standard module template with centrally-managed tooling and standards.

## Key Commands

Commands assume a `Makefile` exists (copy from `.claude/Makefile-example` if missing):

```bash
make bootstrap        # Install Python dependencies
make install-hooks    # Install git pre-commit and commit-msg hooks
make test             # Run all tests
make test-keep        # Run tests, keep AWS resources for debugging
make test-clean       # Run tests, destroy AWS resources after (use before PR)
make lint             # Check terraform fmt and yamllint
make fmt              # Format terraform files + black for Python
make clean            # Remove .pytest_cache and .terraform directories
```

Run a single test:
```bash
pytest -xvvs -k "test_name" tests/test_module.py
```

Default test region: `us-west-2`. Test role: `arn:aws:iam::303467602807:role/openvpn-tester`.

## Managed Files — Do Not Edit

Many files are managed by Terraform in the [github-control](https://github.com/infrahouse8/github-control) repository. Edits will be overwritten. These include:

- `.claude/CODING_STANDARD.md`, `.claude/Makefile-example`, `.claude/agents/terraform-module-reviewer.md`
- `.terraform-docs.yml`, `mkdocs.yml`, `cliff.toml`
- `hooks/pre-commit`, `hooks/commit-msg`
- `.github/workflows/` (all workflow files)

Changes to these must be made via PR in github-control.

## Commit Message Format

Uses [Conventional Commits](https://www.conventionalcommits.org/) enforced by `hooks/commit-msg`:

```
feat: Add support for custom IAM policies
fix: Correct security group ingress rules
docs: Update README with new examples
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`, `security`. Breaking changes use `!` (e.g., `feat!: Remove deprecated variable`).

## Testing

- Framework: pytest with `pytest-infrahouse` fixtures
- Tests create real AWS infrastructure (not mocked)
- Tests should cover multiple AWS provider versions (v5 and v6)
- Test selector defaults to `aws6` (configurable via `TEST_SELECTOR` Make variable)

## Release Process

1. Tag with semver: `git tag v1.0.0`
2. Push the tag: `git push origin v1.0.0`
3. GitHub Actions generates changelog via `git-cliff` and creates a GitHub Release

## Architecture Notes

- **Terraform code** goes in root `.tf` files (`main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`)
- **Tests** go in `tests/test_module.py`
- **Examples** go in `examples/` directory
- **Documentation** is built with MkDocs (Material theme) from `docs/` and deployed to GitHub Pages
- **README.md** uses `terraform-docs` for auto-generated sections between `<!-- BEGIN_TF_DOCS -->` / `<!-- END_TF_DOCS -->` markers

## Claude Agents and Commands

- `/review-local` — Run Terraform module review locally (generates `.claude/reviews/terraform-module-review.md`)
- `/generate-excalidraw` — Generate Excalidraw architecture diagram from the Terraform module
