# 보안 그룹: 인터넷 → EC2(웹 80) → RDS(5432). HTTPS 는 쓰지 않으므로 443 은 열지 않는다
# EC2 접속은 SSM Session Manager 로 하므로 SSH(22) 는 열지 않는다.
resource "aws_security_group" "ec2" {
  name        = "${var.name}-ec2"
  description = "EC2 - web, backend, pipeline"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name}-ec2" }
}

resource "aws_vpc_security_group_ingress_rule" "ec2_web" {
  for_each          = toset(["80"])
  security_group_id = aws_security_group.ec2.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = tonumber(each.value)
  to_port           = tonumber(each.value)
  ip_protocol       = "tcp"
}

# 공공데이터 API 수집, S3, Bedrock, 패키지 설치 등
resource "aws_vpc_security_group_egress_rule" "ec2_all" {
  security_group_id = aws_security_group.ec2.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "database" {
  name        = "${var.name}-database"
  description = "RDS PostgreSQL - EC2 only"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name}-database" }
}

resource "aws_vpc_security_group_ingress_rule" "database_from_ec2" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.ec2.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}
