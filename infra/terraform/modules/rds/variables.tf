variable "name" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "security_group_id" {
  type = string
}

variable "engine_major_version" {
  type    = string
  default = "17"
}

variable "instance_class" {
  type    = string
  default = "db.t3.small"
}

variable "db_name" {
  type    = string
  default = "pill"
}

variable "username" {
  type    = string
  default = "pill_admin"
}

variable "allocated_storage" {
  description = "GiB. RDS PostgreSQL gp3 최소 20"
  type        = number
  default     = 20
}

variable "max_allocated_storage" {
  description = "부족하면 이 크기까지 자동 확장 (늘어난 만큼만 과금)"
  type        = number
  default     = 50
}

variable "multi_az" {
  type    = bool
  default = false
}

variable "backup_retention_days" {
  type    = number
  default = 7
}

variable "master_password_rotation_days" {
  description = "마스터 비밀번호 자동 교체 주기 (일, 최대 1000)"
  type        = number
  default     = 365
}

variable "deletion_protection" {
  description = "true 면 삭제 방지. 프로젝트 종료 후 지울 때는 false 로 바꿔 apply 한 뒤 destroy"
  type        = bool
  default     = true
}
