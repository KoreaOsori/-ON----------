# 구성: VPC + EC2 1대(웹·백엔드·파이프라인) + RDS PostgreSQL 1대(gold / rag 스키마) + S3 데이터 버킷 + Secrets Manager
locals {
  name = "${var.project}-${var.environment}"
}

data "aws_caller_identity" "current" {}

module "network" {
  source = "../../modules/network"
  name   = local.name
}

module "security" {
  source = "../../modules/security"
  name   = local.name
  vpc_id = module.network.vpc_id
}

module "data_bucket" {
  source      = "../../modules/s3"
  bucket_name = "${var.project}-data-${data.aws_caller_identity.current.account_id}"
}

module "secrets" {
  source = "../../modules/secrets"
  name   = "${var.project}/${var.environment}"
  keys   = ["E_Drug_API", "FOOD_SAFETY_API", "JWT_SECRET_KEY"]
}

module "rds" {
  source                = "../../modules/rds"
  name                  = local.name
  subnet_ids            = module.network.private_subnet_ids
  security_group_id     = module.security.database_sg_id
  instance_class        = var.rds_instance_class
  allocated_storage     = var.rds_allocated_storage
  max_allocated_storage = var.rds_max_allocated_storage
}

module "ec2" {
  source            = "../../modules/ec2"
  name              = local.name
  instance_type     = var.ec2_instance_type
  subnet_id         = module.network.public_subnet_ids[0]
  security_group_id = module.security.ec2_sg_id
  data_bucket_arn   = module.data_bucket.bucket_arn
  secret_arns       = [module.secrets.app_secret_arn, module.rds.master_user_secret_arn]
}
