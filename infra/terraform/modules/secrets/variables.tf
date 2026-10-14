variable "name" {
  type = string
}

variable "keys" {
  description = "시크릿에 만들어 둘 키 목록 (값은 빈 문자열로 생성, 직접 채움)"
  type        = list(string)
}

variable "recovery_window_in_days" {
  description = "삭제 후 복구 대기 기간 (0 이면 즉시 삭제)"
  type        = number
  default     = 7
}
