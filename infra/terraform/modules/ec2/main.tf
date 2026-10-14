# EC2 1대: 프론트엔드, 백엔드, 데이터 파이프라인(수집 → silver → gold), 청킹·임베딩을 모두 여기서 실행한다.
# 접속은 SSM Session Manager (SSH 키·22번 포트 없음). 고정 IP(Elastic IP)로 웹 주소가 바뀌지 않게 한다.

# Amazon Linux 2023 최신 AMI (SSM 에이전트 기본 설치)
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-ec2"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
}

# SSM Session Manager 접속
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "app" {
  # 데이터 버킷 읽기·쓰기 (bronze/silver/gold)
  statement {
    actions   = ["s3:ListBucket"]
    resources = [var.data_bucket_arn]
  }
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${var.data_bucket_arn}/*"]
  }
  # API 키, DB 비밀번호 읽기
  statement {
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = var.secret_arns
  }
  # LLM, 임베딩
  statement {
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "app" {
  name   = "${var.name}-ec2-app"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.app.json
}

resource "aws_iam_instance_profile" "this" {
  name = "${var.name}-ec2"
  role = aws_iam_role.this.name
}

resource "aws_instance" "this" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.security_group_id]
  iam_instance_profile   = aws_iam_instance_profile.this.name

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size
    encrypted   = true
  }

  # 인스턴스 메타데이터는 토큰 방식(IMDSv2)만 허용
  metadata_options {
    http_tokens = "required"
  }

  tags = { Name = "${var.name}-ec2" }

  lifecycle {
    # 새 AMI 가 나올 때마다 인스턴스를 다시 만들지 않는다
    ignore_changes = [ami]
  }
}

resource "aws_eip" "this" {
  domain   = "vpc"
  instance = aws_instance.this.id
  tags     = { Name = "${var.name}-ec2" }
}
