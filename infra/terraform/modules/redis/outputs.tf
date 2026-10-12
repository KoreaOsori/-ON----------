output "primary_endpoint" {
  value = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "redis_url" {
  description = "TLS 접속 URL"
  value       = "rediss://${aws_elasticache_replication_group.this.primary_endpoint_address}:6379/0"
}
