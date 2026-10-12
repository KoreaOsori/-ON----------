# 앱 비밀값 묶음. JWT 키는 자동 생성하고, 나머지(OAuth, 공공데이터 키)는 콘솔/CLI 로 값을 채운다.
# 값을 수동으로 바꿔도 terraform 이 덮어쓰지 않도록 secret_string 변경은 무시한다.
resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.name}/app"
  description             = "yakon backend application secrets"
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    JWT_SECRET_KEY          = random_password.jwt.result
    KAKAO_CLIENT_ID         = ""
    KAKAO_CLIENT_SECRET     = ""
    NAVER_CLIENT_ID         = ""
    NAVER_CLIENT_SECRET     = ""
    GOOGLE_CLIENT_ID        = ""
    GOOGLE_CLIENT_SECRET    = ""
    PUBLIC_DATA_SERVICE_KEY = ""
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}
