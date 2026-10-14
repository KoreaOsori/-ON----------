variable "bucket_name" {
  type = string
}

variable "noncurrent_version_days" {
  description = "덮어써진 이전 버전을 보관하는 기간"
  type        = number
  default     = 30
}

variable "force_destroy" {
  description = "true 면 객체가 남아 있어도 버킷 삭제 가능 (데이터 버킷이라 기본 false)"
  type        = bool
  default     = false
}
