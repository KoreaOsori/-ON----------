import type { RxResult } from "../photo/api"

/** 확정되지 않은 검색 후보를 약으로 간주하지 않고, OCR에서 읽은 이름을 v3에 전달한다. */
export function prescriptionProducts(result: RxResult): string[] {
  const names = result.drugs.length
    ? result.drugs.map((drug) =>
        drug.confirmed || drug.auto
          ? drug.itemName || drug.candidates[0]?.itemName || drug.nameRead || ""
          : drug.nameRead || "",
      )
    : result.candidates.map((drug) => drug.name)
  const products = new Map<string, string>()
  for (const value of names) {
    const name = value.trim()
    if (name) products.set(name.replace(/\s+/g, "").toLowerCase(), name)
  }
  return [...products.values()]
}
