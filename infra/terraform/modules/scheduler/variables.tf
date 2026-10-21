variable "name" {
  type = string
}

variable "instance_id" {
  description = "파이프라인을 실행할 EC2"
  type        = string
}

variable "schedule_expression" {
  description = "실행 시각 (EventBridge Scheduler cron: 분 시 일 월 요일 년)"
  type        = string
  default     = "cron(0 2 10 * ? *)" # 매월 10일 02:00
}

variable "timezone" {
  description = "schedule_expression 과 스냅샷 날짜에 쓰는 시간대"
  type        = string
  default     = "Asia/Seoul"
}

variable "compose_dir" {
  description = "EC2 에서 docker compose 를 실행할 폴더 (저장소의 deploy/ec2)"
  type        = string
  default     = "/home/ec2-user/pill/deploy/ec2"
}

variable "execution_timeout_seconds" {
  description = "SSM 명령 최대 실행 시간 (넘으면 중단). 2026-10-19 전체 실행 5시간 46분(속도 개선 전) 기준 여유 있게"
  type        = number
  default     = 28800 # 8시간
}
