output "app_secret_arn" {
  value = aws_secretsmanager_secret.app.arn
}

# ECS 컨테이너 정의에서 사용할 키 목록
output "app_secret_keys" {
  value = [
    "JWT_SECRET_KEY",
    "KAKAO_CLIENT_ID",
    "KAKAO_CLIENT_SECRET",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "PUBLIC_DATA_SERVICE_KEY",
  ]
}
