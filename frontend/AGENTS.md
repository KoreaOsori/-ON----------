# 약온 프론트엔드

Next.js 16 (App Router) + React 19 + Tailwind CSS v4 + TypeScript. 패키지 매니저는 pnpm.

## 명령어

- `pnpm dev` — 개발 서버 (http://localhost:3000)
- `pnpm build` / `pnpm start` — 프로덕션 빌드 / 실행 (`output: "standalone"`)
- `pnpm lint`, `pnpm typecheck`

## 구조

- `src/app/` — 라우트만 둔다. 페이지 파일은 기능 컴포넌트를 렌더링하는 얇은 진입점.
  - `page.tsx` → 챗봇(홈), `(service)/medicine`, `(service)/pharmacy`, `(service)/mypage`
  - `(service)/layout.tsx` — 홈을 제외한 페이지 공통 `<main>` 래퍼
- `src/features/<기능>/` — 기능 단위 코드. `components/`, `hooks/`, `api.ts`(백엔드 호출), `types.ts`
- `src/components/ui/` — 기능에 종속되지 않는 공용 UI (Modal, Notice, DrugArt, 공용 클래스 `styles.ts`)
- `src/components/layout/` — Header 등 전역 레이아웃
- `src/providers/SessionProvider.tsx` — 로그인 상태·건강정보(데모) 전역 상태
- `src/lib/` — 상수, API 클라이언트(`lib/api/client.ts`)
- `src/mocks/` — 화면용 가상 데이터. 백엔드 연동 시 각 기능의 `api.ts` 호출로 교체한다.
- `src/types/` — 여러 기능이 공유하는 타입

## 규칙

- 상태·이벤트 핸들러를 쓰는 컴포넌트는 파일 상단에 `"use client"`.
- 컴포넌트는 default export.
- 스타일은 Tailwind 유틸리티 클래스. 전역 CSS/테마는 `src/app/globals.css`, `src/styles/`.
- 작은따옴표 문자열에 아포스트로피를 넣지 말 것 (큰따옴표 사용).
