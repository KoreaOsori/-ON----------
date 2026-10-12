variable "bucket_name" {
  type = string
}

variable "cors_allowed_origins" {
  type = list(string)
}

variable "expiration_days" {
  type    = number
  default = 30
}

variable "force_destroy" {
  type    = bool
  default = false
}
