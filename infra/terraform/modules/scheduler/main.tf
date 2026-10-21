# 데이터 파이프라인 정기 실행: EventBridge Scheduler 가 정해진 시각에 SSM Run Command 로 EC2 에서 파이프라인을 돌린다.
# (수집 → bronze 검증 → silver → gold → RDS → 오래된 스냅샷 정리, pipeline/run_pipeline.py)
# 실행 결과(성공/실패, 출력)는 SSM 콘솔 → Run Command → 명령 기록에서 본다. 실패 알림은 두지 않음 (2026-10-21 결정)

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "assume_scheduler" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-pipeline-scheduler"
  assume_role_policy = data.aws_iam_policy_document.assume_scheduler.json
}

# 이 EC2 에 셸 명령 문서 하나만 보낼 수 있다
data "aws_iam_policy_document" "send_command" {
  statement {
    actions = ["ssm:SendCommand"]
    resources = [
      "arn:aws:ssm:${data.aws_region.current.region}::document/AWS-RunShellScript",
      "arn:aws:ec2:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:instance/${var.instance_id}",
    ]
  }
}

resource "aws_iam_role_policy" "send_command" {
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.send_command.json
}

resource "aws_scheduler_schedule" "pipeline" {
  name                         = "${var.name}-pipeline-monthly"
  description                  = "data pipeline: collect -> silver -> gold -> RDS -> snapshot cleanup"
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ssm:sendCommand"
    role_arn = aws_iam_role.this.arn

    input = jsonencode({
      DocumentName = "AWS-RunShellScript"
      InstanceIds  = [var.instance_id]
      Comment      = "monthly data pipeline"
      Parameters = {
        # 파이프라인은 수집 포함 몇 시간 걸린다. 끝날 때까지 기다려야 SSM 기록에 최종 성공/실패가 남는다
        executionTimeout = [tostring(var.execution_timeout_seconds)]
        commands = [
          "set -e",
          "cd ${var.compose_dir}",
          # 지난 정기 실행의 컨테이너(로그)는 지우고, 이번 실행 것만 남긴다 (docker logs 로 볼 수 있게)
          "docker ps -aq --filter 'name=^pipeline-monthly-' --filter status=exited | xargs -r docker rm",
          "sudo -u ec2-user docker compose run -T --name pipeline-monthly-$(TZ=${var.timezone} date +%Y%m%d) data-pipeline", # -T: SSM 에는 터미널이 없음
        ]
      }
    })

    # 명령을 보내는 API 호출 자체가 실패했을 때만 다시 시도한다 (파이프라인 실패를 다시 돌리는 것이 아님)
    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 3
    }
  }
}
