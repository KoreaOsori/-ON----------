variable "name" {
  type = string
}

variable "origin_domain" {
  description = "원본 EC2 도메인 이름 (ec2-…compute-1.amazonaws.com)"
  type        = string
}
