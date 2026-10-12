variable "name" {
  type = string
}

variable "repositories" {
  type    = list(string)
  default = ["frontend", "backend"]
}

variable "keep_images" {
  type    = number
  default = 20
}

variable "force_delete" {
  description = "이미지가 남아 있어도 저장소 삭제 허용 (dev 전용)"
  type        = bool
  default     = false
}
