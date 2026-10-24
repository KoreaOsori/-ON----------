output "service_url" {
  description = "웹사이트 주소 (HTTPS, CloudFront)"
  value       = "https://${module.cdn.domain_name}"
}

output "service_url_http" {
  description = "EC2 직접 주소 (HTTP). 위치 권한 등 https 전용 기능은 동작하지 않음"
  value       = "http://${module.ec2.public_ip}"
}

output "ec2_instance_id" {
  value = module.ec2.instance_id
}

output "ec2_connect" {
  description = "EC2 접속 명령 (SSM Session Manager)"
  value       = "aws ssm start-session --target ${module.ec2.instance_id} --region ${var.region}"
}

output "data_bucket" {
  value = module.data_bucket.bucket_name
}

output "upload_bucket" {
  value = module.uploads_bucket.bucket_name
}

output "rds_endpoint" {
  value = module.rds.address
}

output "rds_db_name" {
  value = module.rds.db_name
}

output "rds_master_secret_arn" {
  description = "DB 마스터 계정 (username, password)"
  value       = module.rds.master_user_secret_arn
}

output "app_secret_name" {
  description = "API 키를 이 시크릿에 채워 넣으세요"
  value       = module.secrets.app_secret_name
}
