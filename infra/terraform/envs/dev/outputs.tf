output "service_url" {
  value = local.origin
}

output "alb_dns_name" {
  value = module.alb.dns_name
}

output "ecr_repository_urls" {
  value = module.ecr.repository_urls
}

output "ecs_cluster_name" {
  value = module.ecs.cluster_name
}

output "ecs_services" {
  value = {
    frontend = module.ecs.frontend_service_name
    backend  = module.ecs.backend_service_name
  }
}

output "uploads_bucket" {
  value = module.uploads.bucket_name
}

output "app_secret_arn" {
  description = "OAuth·공공데이터 키 등을 이 시크릿에 채워 넣으세요"
  value       = module.secrets.app_secret_arn
}

output "rds_endpoint" {
  value = module.rds.address
}
