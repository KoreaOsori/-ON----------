# pill_model 워커 전용 Terraform 스택.
# 팀 스택(infra/terraform/envs/dev)과 같은 state 버킷을 쓰되 키를 다르게 해서 서로 영향을 주지 않는다.
terraform {
  required_version = ">= 1.10" # 팀 스택과 같은 조건 (S3 네이티브 잠금 use_lockfile 사용)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # bucket 은 backend.hcl(gitignore)에서 받는다: terraform init -backend-config=backend.hcl
  backend "s3" {
    key          = "pill-check/dev/pill-model.tfstate" # 팀 키(terraform.tfstate)와 다름 — 절대 바꾸지 말 것
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
      Stack       = "pill-model" # 팀 자원과 구분하기 위한 태그
    }
  }
}
