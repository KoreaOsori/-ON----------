variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "security_group_id" {
  type = string
}

variable "certificate_arn" {
  description = "ACM 인증서 ARN (비우면 HTTP 만 사용)"
  type        = string
  default     = ""
}
