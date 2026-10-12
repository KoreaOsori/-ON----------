output "alb_sg_id" {
  value = aws_security_group.alb.id
}

output "frontend_sg_id" {
  value = aws_security_group.frontend.id
}

output "backend_sg_id" {
  value = aws_security_group.backend.id
}

output "database_sg_id" {
  value = aws_security_group.database.id
}

output "redis_sg_id" {
  value = aws_security_group.redis.id
}
