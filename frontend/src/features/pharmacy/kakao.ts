import type { Coordinates } from "./api"

// 카카오 지도 JavaScript SDK. 키는 카카오 개발자 콘솔의 JavaScript 키이며,
// 콘솔 [플랫폼 > Web] 에 등록한 도메인에서만 동작한다 (브라우저에 공개되는 키).
const MAP_KEY = process.env.NEXT_PUBLIC_MAP_CLIENT_KEY ?? ""

export const hasMapKey = MAP_KEY !== ""

// 이 화면에서 쓰는 SDK 기능만 타입으로 둔다
export type KakaoLatLng = { getLat(): number; getLng(): number }
export type KakaoMap = {
  setBounds(bounds: unknown): void
  panTo(position: KakaoLatLng): void
  relayout(): void
}
export type KakaoMarker = { setMap(map: KakaoMap | null): void; setZIndex(index: number): void }
type KakaoStatus = "OK" | "ZERO_RESULT" | "ERROR"
type Kakao = {
  maps: {
    load(callback: () => void): void
    LatLng: new (lat: number, lng: number) => KakaoLatLng
    LatLngBounds: new () => { extend(position: KakaoLatLng): void }
    Map: new (container: HTMLElement, options: { center: KakaoLatLng; level: number }) => KakaoMap
    Marker: new (options: { position: KakaoLatLng; title?: string; map?: KakaoMap }) => KakaoMarker
    CustomOverlay: new (options: {
      position: KakaoLatLng
      content: HTMLElement | string
      map?: KakaoMap
      zIndex?: number
    }) => { setMap(map: KakaoMap | null): void }
    event: { addListener(target: unknown, type: string, handler: () => void): void }
    services: {
      Status: Record<KakaoStatus, KakaoStatus>
      Geocoder: new () => {
        addressSearch(query: string, callback: (result: { x: string; y: string }[], status: KakaoStatus) => void): void
      }
      Places: new () => {
        keywordSearch(query: string, callback: (result: { x: string; y: string }[], status: KakaoStatus) => void): void
      }
    }
  }
}

declare global {
  interface Window {
    kakao?: Kakao
  }
}

let loading: Promise<Kakao> | null = null

export function loadKakaoMaps(): Promise<Kakao> {
  if (!hasMapKey) return Promise.reject(new Error("NEXT_PUBLIC_MAP_CLIENT_KEY 가 없습니다."))
  loading ??= new Promise<Kakao>((resolve, reject) => {
    const script = document.createElement("script")
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${MAP_KEY}&libraries=services&autoload=false`
    script.onload = () => window.kakao!.maps.load(() => resolve(window.kakao!))
    script.onerror = () => {
      loading = null
      reject(new Error("카카오 지도를 불러오지 못했습니다."))
    }
    document.head.appendChild(script)
  })
  return loading
}

/** 주소("서울 강남구 테헤란로 101") 또는 장소 이름("강남역")을 좌표로 바꾼다 */
export async function findCoordinates(query: string): Promise<Coordinates | null> {
  const { maps } = await loadKakaoMaps()
  const { Status } = maps.services
  const search = (run: (callback: (result: { x: string; y: string }[], status: KakaoStatus) => void) => void) =>
    new Promise<Coordinates | null>((resolve) =>
      run((result, status) =>
        resolve(status === Status.OK && result[0] ? { lat: Number(result[0].y), lng: Number(result[0].x) } : null),
      ),
    )
  return (
    (await search((callback) => new maps.services.Geocoder().addressSearch(query, callback))) ??
    (await search((callback) => new maps.services.Places().keywordSearch(query, callback)))
  )
}

// 링크는 키 없이 동작한다 (카카오맵 URL 규칙: 이름,위도,경도 — 이름에 쉼표·슬래시가 있으면 경로가 깨진다)
const linkName = (name: string) => encodeURIComponent(name.replace(/[,/]/g, " "))

export const kakaoDirectionsUrl = (from: Coordinates | null, to: { name: string; latitude: number; longitude: number }) =>
  `https://map.kakao.com/link/${from ? `from/${linkName("내 위치")},${from.lat},${from.lng}/` : ""}to/${linkName(to.name)},${to.latitude},${to.longitude}`

export const naverPlaceUrl = (name: string, address: string) =>
  `https://map.naver.com/p/search/${encodeURIComponent(`${name} ${address.split(" ").slice(0, 2).join(" ")}`)}`
