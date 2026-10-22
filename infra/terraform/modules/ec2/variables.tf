variable "name" {
  type = string
}

variable "instance_type" {
  type    = string
  default = "t3.medium"
}

variable "subnet_id" {
  description = "퍼블릭 서브넷"
  type        = string
}

variable "security_group_id" {
  type = string
}

variable "root_volume_size" {
  description = "GiB. OS, Docker 이미지, 코드, 파이프라인 작업 파일 (bronze 는 S3 업로드 후 지울 것). 부족하면 늘리면 됨"
  type        = number
  default     = 20
}

variable "data_bucket_arn" {
  type = string
}

variable "upload_bucket_arn" {
  type = string
}

variable "secret_arns" {
  description = "EC2 가 읽을 시크릿 (API 키, RDS 마스터 비밀번호)"
  type        = list(string)
}
