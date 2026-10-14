# 팀 공용 비밀값 묶음 (공공데이터 API 키 등). 값은 콘솔/CLI 로 채운다.
# 값을 수동으로 바꿔도 terraform 이 덮어쓰지 않도록 secret_string 변경은 무시한다.
# DB 마스터 비밀번호는 RDS 가 따로 관리하는 시크릿에 있다 (rds 모듈 출력 master_user_secret_arn).
resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.name}/app"
  description             = "pill-check team shared secrets (API keys)"
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id     = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({ for key in var.keys : key => "" })

  lifecycle {
    ignore_changes = [secret_string]
  }
}
