output "worker_instance_id" {
  value = aws_instance.worker.id
}

# 백엔드는 이 프라이빗 IP로 호출 (정지·시작해도 유지됨)
output "worker_private_ip" {
  value = aws_instance.worker.private_ip
}

output "worker_connect" {
  description = "SSM 접속 명령"
  value       = "aws ssm start-session --target ${aws_instance.worker.id} --region ${var.region}"
}

output "model_bucket" {
  value = aws_s3_bucket.model.bucket
}

# 백엔드 .env 의 PILL_WORKER_URL 값
output "worker_url" {
  value = "http://${aws_instance.worker.private_ip}:8000"
}
