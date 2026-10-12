locals {
  name   = "${var.project}-${var.environment}"
  origin = var.public_origin != "" ? var.public_origin : "http://${module.alb.dns_name}"
}

data "aws_caller_identity" "current" {}

module "network" {
  source = "../../modules/network"
  name   = local.name
  region = var.region
}

module "security" {
  source = "../../modules/security"
  name   = local.name
  vpc_id = module.network.vpc_id
}

module "ecr" {
  source       = "../../modules/ecr"
  name         = var.project
  force_delete = true
}

module "uploads" {
  source        = "../../modules/s3"
  bucket_name   = "${local.name}-uploads-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
  # 도메인 연결 전에는 ALB 주소에서 업로드하므로 함께 허용
  cors_allowed_origins = distinct(compact([var.public_origin, "http://${module.alb.dns_name}", "http://localhost:3000"]))
}

module "rds" {
  source            = "../../modules/rds"
  name              = local.name
  subnet_ids        = module.network.private_subnet_ids
  security_group_id = module.security.database_sg_id
}

module "redis" {
  source            = "../../modules/redis"
  name              = local.name
  subnet_ids        = module.network.private_subnet_ids
  security_group_id = module.security.redis_sg_id
}

module "secrets" {
  source                  = "../../modules/secrets"
  name                    = "${var.project}/${var.environment}"
  recovery_window_in_days = 0
}

module "alb" {
  source            = "../../modules/alb"
  name              = local.name
  vpc_id            = module.network.vpc_id
  subnet_ids        = module.network.public_subnet_ids
  security_group_id = module.security.alb_sg_id
  certificate_arn   = var.certificate_arn
}

module "ecs" {
  source = "../../modules/ecs"
  name   = local.name
  region = var.region

  private_subnet_ids         = module.network.private_subnet_ids
  frontend_security_group_id = module.security.frontend_sg_id
  backend_security_group_id  = module.security.backend_sg_id
  frontend_target_group_arn  = module.alb.frontend_target_group_arn
  backend_target_group_arn   = module.alb.backend_target_group_arn

  frontend = {
    image         = "${module.ecr.repository_urls["frontend"]}:${var.image_tag}"
    cpu           = 256
    memory        = 512
    desired_count = 1
  }
  backend = {
    image         = "${module.ecr.repository_urls["backend"]}:${var.image_tag}"
    cpu           = 512
    memory        = 1024
    desired_count = 1
  }

  backend_environment = {
    APP_ENV                   = var.environment
    LOG_LEVEL                 = "INFO"
    RUN_MIGRATIONS            = "true" # dev: 컨테이너 시작 시 alembic upgrade head
    CORS_ORIGINS              = local.origin
    FRONTEND_URL              = local.origin
    OAUTH_REDIRECT_BASE_URL   = "${local.origin}/auth/callback"
    DB_HOST                   = module.rds.address
    DB_PORT                   = tostring(module.rds.port)
    DB_NAME                   = module.rds.db_name
    REDIS_URL                 = module.redis.redis_url
    AWS_REGION                = var.region
    S3_UPLOAD_BUCKET          = module.uploads.bucket_name
    BEDROCK_ENABLED           = tostring(var.bedrock_enabled)
    BEDROCK_REGION            = var.region
    BEDROCK_MODEL_ID          = var.bedrock_model_id
    BEDROCK_FALLBACK_MODEL_ID = var.bedrock_fallback_model_id
    OCR_PROVIDER              = var.ocr_provider
    DRUG_DATA_SOURCE          = var.drug_data_source
    DEMO_LOGIN_ENABLED        = "false"
  }

  backend_secrets = merge(
    {
      DB_USERNAME = "${module.rds.master_user_secret_arn}:username::"
      DB_PASSWORD = "${module.rds.master_user_secret_arn}:password::"
    },
    { for key in module.secrets.app_secret_keys : key => "${module.secrets.app_secret_arn}:${key}::" },
  )
  secret_arns = [module.rds.master_user_secret_arn, module.secrets.app_secret_arn]

  uploads_bucket_arn = module.uploads.bucket_arn

  # ECS 서비스는 ALB 리스너·규칙이 만들어진 뒤에 생성
  depends_on = [module.alb]
}
