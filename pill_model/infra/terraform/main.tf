# pill_model 워커: EC2 1대 + 전용 SG + IAM 역할 + 모델 버킷.
# 팀 자원(VPC·서브넷·백엔드 SG·데이터 버킷)은 data 로 존재만 확인하고 절대 수정하지 않는다.

data "aws_caller_identity" "current" {}

# ---------- 팀 자원: 읽기만 ----------
data "aws_vpc" "team" {
  id = var.vpc_id
}

data "aws_subnet" "public" {
  id = var.subnet_id
}

data "aws_security_group" "backend" {
  id = var.backend_sg_id
}

data "aws_s3_bucket" "data" {
  bucket = var.data_bucket_name
}

# 업로드 버킷 (팀 Terraform 소유, 2026-10-22 생성 확인) — 읽기만. 이름이 빈 값이면 조회 생략
data "aws_s3_bucket" "upload" {
  count  = var.upload_bucket_name == "" ? 0 : 1
  bucket = var.upload_bucket_name
}

# 처방전 LLM 교차 리전 추론 프로필 — 실제로 요청이 가는 기반 모델 ARN 목록을 AWS에서 받아온다
# (리전 목록을 코드에 직접 쓰지 않기 위해. 10-23 조회: us-east-1·us-east-2·us-west-2)
data "aws_bedrock_inference_profile" "rx_llm" {
  inference_profile_id = var.bedrock_inference_profile_id
}

# Amazon Linux 2023 최신 AMI (SSM 에이전트 기본 설치) — 팀 EC2 모듈과 같은 방식
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

locals {
  model_bucket_name = "${var.name_prefix}-model-${data.aws_caller_identity.current.account_id}"
  # 버킷이 실제로 있는지 data 조회로 확인한 ARN을 쓴다 (이름 오타면 plan 단계에서 실패)
  upload_bucket_arn = var.upload_bucket_name == "" ? null : data.aws_s3_bucket.upload[0].arn
}

# ---------- 모델 버킷 (models/v5/…, crops/…) ----------
resource "aws_s3_bucket" "model" {
  bucket = local.model_bucket_name
  # 동의받은 crop 이 실수로 지워지지 않게 false. destroy 전에 버킷을 직접 비워야 한다 (README 참고)
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "model" {
  bucket                  = aws_s3_bucket.model.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "model" {
  bucket = aws_s3_bucket.model.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "model" {
  bucket = aws_s3_bucket.model.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# HTTPS 외 접근 차단 (팀 데이터 버킷과 같은 정책)
resource "aws_s3_bucket_policy" "model" {
  bucket = aws_s3_bucket.model.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.model.arn, "${aws_s3_bucket.model.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.model]
}

# ---------- 워커 SG (새로 생성, 팀 SG에는 규칙 추가 안 함) ----------
resource "aws_security_group" "worker" {
  name        = "${var.name_prefix}-sg"
  description = "pill_model worker: TCP 8000 from backend SG only"
  vpc_id      = data.aws_vpc.team.id
  tags        = { Name = "${var.name_prefix}-sg" }

  lifecycle {
    # 서브넷·백엔드 SG가 같은 VPC인지 apply 전에 확인 (ID 오타 방지)
    precondition {
      condition     = data.aws_subnet.public.vpc_id == var.vpc_id
      error_message = "subnet_id 가 vpc_id 와 다른 VPC에 있습니다."
    }
    precondition {
      condition     = data.aws_security_group.backend.vpc_id == var.vpc_id
      error_message = "backend_sg_id 가 vpc_id 와 다른 VPC에 있습니다."
    }
    precondition {
      condition     = data.aws_subnet.public.map_public_ip_on_launch
      error_message = "subnet_id 가 퍼블릭 서브넷이 아닙니다 (NAT가 없어 인터넷·S3 접근 불가)."
    }
  }
}

# 인바운드: 백엔드 SG에서 오는 8000번만 (인터넷 인바운드 없음, 접속은 SSM)
resource "aws_vpc_security_group_ingress_rule" "from_backend" {
  security_group_id            = aws_security_group.worker.id
  referenced_security_group_id = data.aws_security_group.backend.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
  description                  = "worker API from backend"
}

# 아웃바운드 전체 (패키지 설치·S3·SSM)
resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.worker.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "packages, S3, SSM"
}

# ---------- IAM 역할·인스턴스 프로필 ----------
data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "worker" {
  name               = "${var.name_prefix}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
}

# SSM Session Manager 접속
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# 최소 권한: 필요한 경로만 열어 둔다
data "aws_iam_policy_document" "worker" {
  # 모델 버킷: 모델 내려받기 + 동의한 crop 저장
  statement {
    sid       = "ModelList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.model.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["models/*"]
    }
  }
  statement {
    sid       = "ModelRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.model.arn}/models/*"]
  }
  statement {
    sid       = "CropWrite"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.model.arn}/crops/*"]
  }

  # 데이터 버킷(팀): silver 읽기만 → image_url 붙이기
  # 낱알식별 데이터는 별도 테이블이 아니라 drug_product 의 pills 목록 안에 있다 (인프라 담당 확인, 2026-10-23)
  statement {
    sid       = "SilverList"
    actions   = ["s3:ListBucket"]
    resources = [data.aws_s3_bucket.data.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["silver/drug_product/*"]
    }
  }
  statement {
    sid     = "SilverRead"
    actions = ["s3:GetObject"]
    resources = [
      "${data.aws_s3_bucket.data.arn}/silver/_latest.json",
      "${data.aws_s3_bucket.data.arn}/silver/drug_product/*",
    ]
  }

  # 업로드 버킷: 사용자가 올린 알약·처방전 사진 읽기 (버킷 이름이 정해졌을 때만)
  # 백엔드 업로드 key = {purpose}/YYYY/MM/DD/{owner}/{uuid}.{ext}, purpose ∈ {pill, prescription}
  dynamic "statement" {
    for_each = local.upload_bucket_arn == null ? [] : [local.upload_bucket_arn]
    content {
      sid     = "UploadRead"
      actions = ["s3:GetObject"]
      resources = [
        "${statement.value}/pill/*",
        "${statement.value}/prescription/*",
      ]
    }
  }

  # 처방전 LLM (Bedrock Converse). 교차 리전 추론 프로필은 프로필 ARN과
  # 요청이 갈 수 있는 모든 리전의 기반 모델 ARN 양쪽에 권한이 있어야 한다
  statement {
    sid     = "RxLlmInvoke"
    actions = ["bedrock:InvokeModel"]
    resources = concat(
      [data.aws_bedrock_inference_profile.rx_llm.inference_profile_arn],
      [for m in data.aws_bedrock_inference_profile.rx_llm.models : m.model_arn],
    )
  }
}

resource "aws_iam_role_policy" "worker" {
  name   = "${var.name_prefix}-s3"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}

resource "aws_iam_instance_profile" "worker" {
  name = "${var.name_prefix}-role"
  role = aws_iam_role.worker.name
}

# ---------- EC2 ----------
resource "aws_instance" "worker" {
  ami                         = data.aws_ssm_parameter.al2023.value
  instance_type               = var.instance_type
  subnet_id                   = data.aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.worker.id]
  iam_instance_profile        = aws_iam_instance_profile.worker.name
  associate_public_ip_address = true # NAT 없음 → 퍼블릭 IP로 밖에 나감 (인바운드는 SG가 막음)
  user_data                   = file("${path.module}/user_data.sh")
  # 키 페어 없음: 접속은 SSM

  # unlimited 이면 CPU를 오래 쓸 때 추가 요금 → standard 로 고정
  credit_specification {
    cpu_credits = "standard"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size
    encrypted   = true
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 만 허용
    # 1 이면 Docker 컨테이너 안에서 IAM 역할 자격 증명을 못 받는다 (네트워크 홉이 하나 더 있음)
    http_put_response_hop_limit = 2
  }

  tags = { Name = var.name_prefix }

  lifecycle {
    # 새 AMI 가 나올 때마다 인스턴스를 다시 만들지 않는다 (팀 EC2와 같은 방식)
    ignore_changes = [ami]
  }
}
