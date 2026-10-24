# CloudFront: EC2(nginx, http:80) 앞에서 https 를 제공한다. 기본 *.cloudfront.net 인증서를 쓰므로 도메인·ACM 이 필요 없다.
# 브라우저의 위치 권한(Geolocation)·카메라 등은 https 에서만 동작한다 — 2026-10-24 내 주변 약국 위치 조회를 위해 추가
# 페이지·API 는 캐시하지 않고 그대로 전달하고, Next.js 빌드 파일(/_next/static, 파일명에 해시 포함)만 캐시한다.

# AWS 관리형 정책 (이름으로 조회)
data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

# Host 를 뺀 요청 헤더·쿠키·쿼리 전부 전달 (Host 는 원본 도메인으로 바뀜. nginx 는 server_name _ 라 상관없음)
data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_distribution" "this" {
  enabled         = true
  comment         = "${var.name} web (https -> EC2 http)"
  is_ipv6_enabled = true
  http_version    = "http2and3"
  price_class     = "PriceClass_200" # 한국·일본 엣지 포함 (PriceClass_100 은 북미·유럽만)

  origin {
    origin_id   = "ec2"
    domain_name = var.origin_domain # IP 는 쓸 수 없어 EC2 도메인 이름 사용
    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60 # 기본 한도 최대값. 스트리밍은 바이트 사이 간격이라 LLM 응답도 이 안에 들어옴
      origin_keepalive_timeout = 60
    }
  }

  default_cache_behavior {
    target_origin_id         = "ec2"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    compress                 = true
  }

  ordered_cache_behavior {
    path_pattern           = "/_next/static/*"
    target_origin_id       = "ec2"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = { Name = "${var.name}-web" }
}
