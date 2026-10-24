// FastAPI 백엔드 호출 공통 클라이언트
// - 로컬: NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
// - AWS: 빈 값 → 같은 도메인의 /api/* 를 ALB가 백엔드로 라우팅
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? ""
const API_PREFIX = "/api/v1"

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message)
  }
}

let accessToken: string | null = null
// 액세스 토큰이 만료(401)되면 한 번 재발급을 시도하는 함수 (SessionProvider 가 등록)
let refreshAccessToken: (() => Promise<boolean>) | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function setTokenRefresher(refresher: (() => Promise<boolean>) | null) {
  refreshAccessToken = refresher
}

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown
  query?: Record<string, string | number | boolean | undefined>
  /** 경로 앞부분. 기본 /api/v1. LLM(/api/llm/v3)처럼 다른 백엔드 앱을 부를 때 바꾼다 */
  prefix?: string
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}, retried = false): Promise<T> {
  const { body, query, headers, prefix = API_PREFIX, ...init } = options
  const url = new URL(`${API_BASE_URL}${prefix}${path}`, globalThis.location?.origin ?? "http://localhost")
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined) url.searchParams.set(key, String(value))
  })

  const response = await fetch(url, {
    ...init,
    credentials: "include",
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (response.status === 401 && accessToken && refreshAccessToken && !retried && (await refreshAccessToken()))
    return apiFetch<T>(path, options, true)

  if (!response.ok) {
    const detail = await response.json().catch(() => undefined)
    throw new ApiError(response.status, `API 요청 실패: ${response.status}`, detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
