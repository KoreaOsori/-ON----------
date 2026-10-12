variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "frontend_security_group_id" {
  type = string
}

variable "backend_security_group_id" {
  type = string
}

variable "frontend_target_group_arn" {
  type = string
}

variable "backend_target_group_arn" {
  type = string
}

variable "cpu_architecture" {
  description = "X86_64 | ARM64 (이미지 빌드 플랫폼과 일치해야 함)"
  type        = string
  default     = "X86_64"
}

variable "frontend" {
  type = object({
    image         = string
    cpu           = number
    memory        = number
    desired_count = number
  })
}

variable "backend" {
  type = object({
    image         = string
    cpu           = number
    memory        = number
    desired_count = number
  })
}

variable "backend_environment" {
  description = "백엔드 일반 환경변수"
  type        = map(string)
}

variable "backend_secrets" {
  description = "백엔드 시크릿 환경변수 (이름 => Secrets Manager valueFrom)"
  type        = map(string)
}

variable "secret_arns" {
  description = "실행 역할이 읽을 수 있는 시크릿 ARN 목록"
  type        = list(string)
}

variable "uploads_bucket_arn" {
  type = string
}

variable "log_retention_days" {
  type    = number
  default = 30
}
