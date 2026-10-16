variable "name" {
  description = "리소스 이름 접두사 (예: pill-check-dev)"
  type        = string
}

variable "cidr_block" {
  type    = string
  default = "10.20.0.0/16"
}

variable "az_count" {
  description = "사용할 가용영역 수 (RDS 서브넷 그룹은 최소 2개 필요)"
  type        = number
  default     = 2
}
