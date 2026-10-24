output "domain_name" {
  description = "https 웹 주소 도메인 (xxxx.cloudfront.net)"
  value       = aws_cloudfront_distribution.this.domain_name
}

output "distribution_id" {
  value = aws_cloudfront_distribution.this.id
}
