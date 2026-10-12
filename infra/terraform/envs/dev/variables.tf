variable "project" {
  type    = string
  default = "yakon"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "region" {
  type    = string
  default = "ap-northeast-2"
}

variable "image_tag" {
  description = "배포할 컨테이너 이미지 태그 (CI 에서 git SHA 등으로 지정)"
  type        = string
  default     = "latest"
}

variable "certificate_arn" {
  description = "ACM 인증서 ARN. 도메인 연결 전에는 비워두면 ALB HTTP 로 접속"
  type        = string
  default     = ""
}

variable "public_origin" {
  description = "서비스 접속 주소 (CORS·OAuth redirect 용). 비우면 ALB DNS 를 http 로 사용"
  type        = string
  default     = ""
}

variable "bedrock_enabled" {
  description = "Bedrock 모델 접근 권한 확인 후 true 로 변경"
  type        = bool
  default     = false
}

variable "bedrock_model_id" {
  type    = string
  default = "anthropic.claude-opus-5-5"
}

variable "bedrock_fallback_model_id" {
  type    = string
  default = "anthropic.claude-opus-4-8"
}

variable "ocr_provider" {
  description = "mock | claude | textract"
  type        = string
  default     = "mock"
}

variable "drug_data_source" {
  description = "mock | public_api"
  type        = string
  default     = "mock"
}
