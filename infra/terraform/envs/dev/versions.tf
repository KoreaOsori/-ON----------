terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # bucket 은 bootstrap 출력값(state_bucket)을 사용: terraform init -backend-config=backend.hcl
  backend "s3" {
    key          = "pill-check/dev/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true # 동시에 apply 하지 못하게 잠금 (추가 자원 없음)
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
