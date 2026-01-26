# Hive AWS Deployment
This repository now contains a modular Terraform setup for AWS.

## Structure
- `/infra/terraform/main.tf`: Root configuration.
- `/infra/terraform/modules/vpc`: Reusable networking module.

## How to use
Run `terraform init` and `terraform plan` inside the `/infra/terraform` directory.
