variable "bucket_name" {
  type = string
}

variable "expiration_days" {
  description = "올린 사진을 보관하는 기간 (지나면 자동 삭제)"
  type        = number
  default     = 30
}

variable "allowed_origins" {
  description = "브라우저 직접 업로드를 허용할 웹 주소"
  type        = list(string)
}
