import type { NextConfig } from "next"

// Docker(Windows 바인드 마운트)에서는 파일 변경 이벤트가 전달되지 않아 폴링으로 감시한다
const watchPollMs = Number(process.env.NEXT_WATCH_POLL_MS) || undefined

const nextConfig: NextConfig = {
  // Docker 이미지 경량화를 위해 standalone 산출물 사용 (ECS Fargate 배포)
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  ...(watchPollMs && { watchOptions: { pollIntervalMs: watchPollMs } }),
}

export default nextConfig
