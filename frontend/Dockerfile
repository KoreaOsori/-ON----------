# syntax=docker/dockerfile:1.7
# ---- 약온 프론트엔드 (Next.js standalone) ----
FROM node:22-alpine AS base
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH NEXT_TELEMETRY_DISABLED=1
RUN corepack enable
WORKDIR /app

FROM base AS deps
COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile

# 개발용: 소스는 docker compose 에서 볼륨 마운트, next dev 핫 리로드
# Turbopack 은 Windows 바인드 마운트에서 변경 감지가 안 돼 webpack + 폴링(NEXT_WATCH_POLL_MS) 사용
FROM base AS dev
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 3000
CMD ["pnpm", "dev", "--webpack", "--hostname", "0.0.0.0", "--port", "3000"]

FROM base AS builder
# NEXT_PUBLIC_* 값은 빌드 시점에 번들에 포함된다
ARG NEXT_PUBLIC_API_BASE_URL=""
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_MAP_CLIENT_KEY=""
ENV NEXT_PUBLIC_MAP_CLIENT_KEY=$NEXT_PUBLIC_MAP_CLIENT_KEY
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S nodejs -g 1001 && adduser -S nextjs -u 1001 -G nodejs
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1
CMD ["node", "server.js"]
