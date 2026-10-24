variable "region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "pill-check"
}

variable "environment" {
  type    = string
  default = "dev"
}

# 이 스택이 새로 만드는 자원 이름 앞에 붙는다
variable "name_prefix" {
  type    = string
  default = "pill-worker"
}

variable "instance_type" {
  type    = string
  default = "t3.medium"
}

variable "root_volume_size" {
  description = "루트 볼륨 크기(GB). Docker 이미지(torch·PaddleOCR·rembg 모델 포함)가 커서 30GB"
  type        = number
  default     = 30
}

# ---------- 팀 자원 (읽기만). 실제 값은 terraform.tfvars 에만 적는다 ----------
# 이름 태그로 찾지 않고 ID로 받는 이유: 계정의 실제 이름 규칙이 저장소 문서와 달라서 (PLAN 2-1)

variable "vpc_id" {
  description = "백엔드 EC2가 있는 VPC ID"
  type        = string
}

variable "subnet_id" {
  description = "백엔드와 같은 VPC의 퍼블릭 서브넷 ID (NAT 없음 → 퍼블릭이어야 패키지·S3 접근 가능)"
  type        = string
}

variable "backend_sg_id" {
  description = "백엔드 EC2에 붙은 보안 그룹 ID. 워커 8000 포트는 이 SG에서만 허용"
  type        = string
}

variable "data_bucket_name" {
  description = "silver 데이터가 있는 팀 데이터 버킷 이름"
  type        = string
}

variable "bedrock_inference_profile_id" {
  description = "처방전 LLM (config_rx.json 의 llm.model_id 와 같아야 함). 교차 리전 추론 프로필"
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "upload_bucket_name" {
  description = "운영 업로드 버킷 이름 (팀 Terraform이 만듦, pill/ 아래 사진만 읽음). 빈 값이면 해당 권한 생략"
  type        = string
  default     = ""
}
