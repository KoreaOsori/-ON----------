import assert from "node:assert/strict"
import test from "node:test"
import { prescriptionProducts } from "../src/features/chat/prescriptionProducts.ts"

const result = (drugs, candidates = []) => ({ drugs, candidates })
const drug = (nameRead, extra = {}) => ({ nameRead, auto: false, candidates: [], ...extra })

test("사진의 모든 제품명을 전달하고 불확실한 후보를 임의로 선택하지 않는다", () => {
  const names = ["어린이타이레놀산160밀리그램(아세트아미노펜)", "타이레놀정500밀리그램(아세트아미노펜)", "알레그라정120밀리그램(펙소페나딘염산염)", "케보린정(수출명:돌코린정)", "타이레놀콜드-에스정"]
  assert.deepEqual(prescriptionProducts(result(names.map((name) => drug(name, {
    candidates: [{ itemName: "다른 후보" }],
  })))), names)
})

test("확정 품목명과 자동 매칭을 사용하고 공백 중복을 제거한다", () => {
  assert.deepEqual(prescriptionProducts(result([
    drug("읽은 이름", { confirmed: true, itemName: "확정약" }),
    drug("다른 이름", { auto: true, candidates: [{ itemName: "자동약" }] }),
    drug("확정 약"), drug(null), drug(" "),
  ])), ["확정 약", "자동약"])
})

test("기존 OCR 응답도 지원하고 인식 실패 시 빈 목록을 반환한다", () => {
  assert.deepEqual(prescriptionProducts(result([], [{ name: "약A" }, { name: "약B" }])), ["약A", "약B"])
  assert.deepEqual(prescriptionProducts(result([drug(null, { candidates: [{ itemName: "추측" }] })])), [])
})

test("11개 이상을 조용히 잘라내지 않아 호출자가 초과를 알 수 있다", () => {
  assert.equal(prescriptionProducts(result(Array.from({ length: 11 }, (_, i) => drug(`약${i}`)))).length, 11)
})
