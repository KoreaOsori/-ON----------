output "instance_id" {
  value = aws_instance.this.id
}

output "public_ip" {
  value = aws_eip.this.public_ip
}

# 브라우저가 IP 대신 EC2 도메인 이름(ec2-…compute-1.amazonaws.com)으로 접속할 때도 업로드 CORS 를 허용하기 위해
output "public_dns" {
  value = aws_eip.this.public_dns
}

output "role_name" {
  value = aws_iam_role.this.name
}
