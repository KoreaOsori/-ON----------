variable "name" {
  type = string
}

variable "recovery_window_in_days" {
  description = "삭제 후 복구 대기 기간 (0 이면 즉시 삭제, dev 에서만 권장)"
  type        = number
  default     = 7
}
