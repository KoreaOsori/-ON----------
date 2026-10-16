variable "project" {
  type    = string
  default = "pill-check"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "ec2_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "rds_instance_class" {
  type    = string
  default = "db.t3.small"
}

variable "rds_allocated_storage" {
  description = "GiB"
  type        = number
  default     = 20
}

variable "rds_max_allocated_storage" {
  description = "GiB. 부족하면 여기까지 자동 확장"
  type        = number
  default     = 50
}
