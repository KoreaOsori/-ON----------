# PostgreSQL: 프라이빗 서브넷, 스토리지 암호화, 마스터 비밀번호는 RDS 가 Secrets Manager 에서 관리
# 인스턴스 1대 안에 데이터베이스 1개, 스키마 gold(정형) / rag(pgvector) 로 나눠 쓴다 (스키마·확장은 직접 생성)
resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-db"
  subnet_ids = var.subnet_ids
}

resource "aws_db_parameter_group" "this" {
  name   = "${var.name}-postgres${var.engine_major_version}"
  family = "postgres${var.engine_major_version}"

  # TLS 접속 강제
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot" # AWS 에 저장된 값과 맞춰 plan 에 매번 변경이 뜨지 않게 함
  }
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name}-postgres"
  engine         = "postgres"
  engine_version = var.engine_major_version
  instance_class = var.instance_class

  db_name                     = var.db_name
  username                    = var.username
  manage_master_user_password = true

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.security_group_id]
  parameter_group_name   = aws_db_parameter_group.this.name
  publicly_accessible    = false
  multi_az               = var.multi_az

  backup_retention_period    = var.backup_retention_days
  auto_minor_version_upgrade = true
  deletion_protection        = var.deletion_protection
  skip_final_snapshot        = !var.deletion_protection
  final_snapshot_identifier  = var.deletion_protection ? "${var.name}-postgres-final" : null

  performance_insights_enabled = false
}

# RDS 가 만든 마스터 비밀번호 시크릿의 자동 교체 주기 (RDS 기본값 7일)
# 시연용 프로젝트라 교체 때마다 접속이 끊기지 않도록 길게 둔다. rotate_immediately=false 라 적용해도 비밀번호는 바뀌지 않는다
resource "aws_secretsmanager_secret_rotation" "master_password" {
  secret_id          = aws_db_instance.this.master_user_secret[0].secret_arn
  rotate_immediately = false

  rotation_rules {
    automatically_after_days = var.master_password_rotation_days
  }
}
