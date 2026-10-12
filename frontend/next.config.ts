import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  // Docker 이미지 경량화를 위해 standalone 산출물 사용 (ECS Fargate 배포)
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
}

export default nextConfig
