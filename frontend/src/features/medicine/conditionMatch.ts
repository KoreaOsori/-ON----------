/**
 * 지병 주의: 사용자가 입력한 지병을 약 허가 문서 "다음 환자에는 투여하지 말 것"(전문의약품)·"다음과 같은 사람은 이 약을
 * 복용하지 말 것"(일반의약품) 항목 줄과 맞춘다 (브라우저에서만, 서버로 보내지 않음).
 * 식약처 DUR 에는 지병-약 금기가 없어서, 허가 문서 문장으로 찾는 것이다 (판정이 아니라 근거 문장 안내).
 *
 * - "투여하지 말 것": 항목이 "질환 목록 + 환자" 꼴이고 그 목록의 한 항목이 지병 이름 그 자체 (예: "3) 고혈압 환자")
 * - "주의": 그 밖에 지병이 언급된 줄 (예: "6) 심한 고혈압 환자", "중증 간장애 환자", "기관지 천식 병력…") — 원문을 보고 판단
 * 2026-10-23 로컬 gold 전수 검토: 문서 전체가 아니라 이 항목 안에서만 찾아야 한다 (이상반응·임상시험 문장이 대량으로 걸림)
 */

type Condition = {
  /** 사용자 입력에 이 말이 있으면 이 지병으로 본다 */
  triggers: (string | RegExp)[]
  /** 항목 줄에서 찾는 표기 */
  mention: RegExp
  /** "투여하지 말 것"으로 볼 목록 항목 (정확히 같을 때만) */
  names: string[]
}

const CONDITIONS: Record<string, Condition> = {
  고혈압: { triggers: ["고혈압"], mention: /(?<!폐|폐동맥\s?|문맥\s?|두개내\s?)고혈압/, names: ["고혈압", "고혈압증"] },
  당뇨: { triggers: ["당뇨"], mention: /당뇨/, names: ["당뇨병", "당뇨"] },
  천식: { triggers: ["천식"], mention: /천식/, names: ["천식", "기관지 천식", "기관지천식"] },
  녹내장: { triggers: ["녹내장"], mention: /녹내장/, names: ["녹내장"] },
  간질환: {
    triggers: ["간질환", "간장애", "간염", "간경화", "간경변", "지방간", "간기능", "간부전"],
    mention: /간장애|간질환|간기능\s?장애|간부전|간경변/,
    names: ["간장애", "간질환", "간기능장애", "간부전", "간경변"],
  },
  신장질환: {
    triggers: ["신장", "신부전", "콩팥", "신기능", "투석"],
    // "외상성 전신장애", "부신부전", "부신기능 장애"는 신장이 아니다
    mention: /(?<![전부])신장애|(?<!부)신부전|신장질환|(?<!부)신기능\s?장애/,
    names: ["신장애", "신부전", "신장질환", "신기능장애"],
  },
  심부전: { triggers: ["심부전"], mention: /심부전/, names: ["심부전", "울혈성 심부전", "울혈성심부전"] },
  위궤양: {
    triggers: ["위궤양", "소화성궤양", "십이지장궤양"],
    mention: /위궤양|소화성\s?궤양|소화궤양/,
    names: ["소화성궤양", "위궤양", "소화궤양"],
  },
  전립선비대: { triggers: ["전립선", "전립샘"], mention: /전립[선샘]비대/, names: ["전립선비대", "전립선비대증"] },
  // 항진·저하는 반대 상태라 따로 본다 (입력에 "항진"/"저하"가 있으면 그쪽, 없으면 갑상선 질환 전체)
  갑상선기능항진증: {
    triggers: ["갑상선기능항진", "갑상샘기능항진", "갑상선항진", "갑상샘항진"],
    mention: /(?<!부)갑상[선샘]\s?기능\s?항진|(?<!부)갑상[선샘]\s?항진|(?<!부)갑상[선샘]\s?(질환|기능\s?이상)/,
    names: ["갑상선기능항진증", "갑상샘기능항진증", "갑상선기능항진", "갑상샘기능항진", "갑상선 질환", "갑상샘 질환"],
  },
  갑상선기능저하증: {
    triggers: ["갑상선기능저하", "갑상샘기능저하", "갑상선저하", "갑상샘저하"],
    mention: /(?<!부)갑상[선샘]\s?기능\s?저하|(?<!부)갑상[선샘]\s?저하|(?<!부)갑상[선샘]\s?(질환|기능\s?이상)/,
    names: ["갑상선기능저하증", "갑상샘기능저하증", "갑상선 질환", "갑상샘 질환"],
  },
  갑상선질환: {
    triggers: ["갑상선", "갑상샘"],
    mention: /(?<!부)갑상[선샘]/,
    names: ["갑상선기능항진증", "갑상샘기능항진증", "갑상선기능저하증", "갑상샘기능저하증", "갑상선 질환", "갑상샘 질환"],
  },
  // "간질환", "간질성 폐렴", "말기·중증(의) 간질환자"는 뇌전증이 아니다 (그 밖의 "간질환자"는 어느 쪽인지 알 수 없어 둘 다로 본다)
  뇌전증: {
    triggers: ["뇌전증", /간질(?!환|성)/, "경련"],
    mention: /뇌전증|(?<!말기\s?|중증의?\s?)간질(?!환(?!자)|성)/,
    names: ["뇌전증", "간질"],
  },
  통풍: { triggers: ["통풍"], mention: /통풍/, names: ["통풍"] },
  저혈압: { triggers: ["저혈압"], mention: /저혈압/, names: ["저혈압"] },
  고지혈증: { triggers: ["고지혈증", "이상지질혈증", "콜레스테롤"], mention: /고지혈증|이상지질혈증/, names: ["고지혈증", "이상지질혈증"] },
}

// 지병이 아니거나 너무 일반적인 말 (그대로 찾으면 거의 모든 줄이 걸린다)
const NOT_A_CONDITION = new Set([
  "없음", "모름", "없어요", "모르겠어요", "기타", "환자", "질환", "질병", "병", "증상", "약", "복용", "복용중", "중", "있음",
  "있어요", "앓고", "치료", "치료중", "진단", "만성", "급성", "경증", "중증", "심한", "약간", "조금",
])
// 정도·조건 표현 (예: "심한 고혈압", "중증 신장애", "조절되지 않는 고혈압", "급성 폐쇄각녹내장", "활동성 소화성궤양")
// 조건이 붙은 항목 ("간장애, 신장애 환자로서 … 투여 중인", "천식, 비염 및 비용종의 증후군")도 "주의"
const QUALIFIER =
  /심한|심각한|중증|중등|중중|조절되지|조절이 ?불가|조절 ?불가|비조절|급성|말기|진행성|불안정|활동성|이차|폐쇄각|협우각|로서|경우|의 ?증후군/
// 번호 항목 "질환 목록 + 환자/사람" (일반의약품 문서는 "다음과 같은 사람은 이 약을 복용하지 말 것" 아래 "… 사람"도 씀)
// 끝에 붙은 괄호(예: "환자(허혈심장병, 고혈압 포함)")는 2번 그룹
const ITEM = /^(?:\d+\)|\(\d+\)|[①-⑳]|-)\s*(.+?)\s*(?:등의|등)?\s*(?:환자|사람)\s*(\([^)]*\))?\.?$/

// 범위를 한정하는 줄 ("<이하 소화성 궤양의 보조시에 한함>", 제형별 "(첩부제)"). 그 아래 항목은 그 경우에만 해당하므로 "주의"
const SCOPE = /^<[^>]*한함>$|^\([^)]*제\)$/

const compact = (text: string) => text.replace(/\s/g, "")

/**
 * 사용자 지병 입력 → 찾을 지병 목록. 쉼표·빗금·줄바꿈으로 나눈 덩어리마다 띄어쓰기를 무시하고 사전과 맞춘다
 * ("고혈압 당뇨" → 고혈압·당뇨, "갑상선 저하증" → 갑상선기능저하증). 사전에 없는 덩어리(예: 부정맥, 궤양성 대장염)는
 * 덩어리째 그대로 찾는다 ("주의"로만)
 */
export function parseConditions(text: string | undefined) {
  const found = new Map<string, Condition | null>()
  for (const segment of (text ?? "").split(/[,/·\n]+/)) {
    const words = segment.split(/\s+/).filter((word) => word && !NOT_A_CONDITION.has(word))
    const joined = compact(words.join(""))
    if (joined.length < 2) continue
    const known = Object.entries(CONDITIONS).filter(([, condition]) =>
      condition.triggers.some((trigger) =>
        typeof trigger === "string" ? joined.includes(trigger) : trigger.test(joined),
      ),
    )
    // 갑상선기능항진증·저하증이 잡히면 갑상선 질환 전체는 빼고 그쪽만
    const specific = known.filter(([name]) => name !== "갑상선질환")
    const hits = specific.some(([name]) => name.startsWith("갑상선")) ? specific : known
    if (hits.length) for (const [name, condition] of hits) found.set(name, condition)
    else found.set(words.join(" "), null)
  }
  return found
}

/** 이 줄이 지병 "투여하지 말 것"(true) / "주의"(false) / 무관(null) */
function classify(line: string, name: string, condition: Condition | null): boolean | null {
  if (!(condition ? condition.mention.test(line) : compact(line).includes(compact(name)))) return null
  const match = line.match(ITEM)
  if (!match) return false
  // 정도·조건이 붙은 항목은 해당 여부를 사용자가 판단해야 하므로 "주의" (목록 어디에 붙었든 보수적으로)
  if (QUALIFIER.test(match[1].replace(/\([^)]*\)/g, ""))) return false
  // 괄호 안의 단계·수치 기준·한정도 조건 (예: "(NYHA II - IV)", "(수축기압 90mmHg 미만)", "(크레아티닌청소율 < 30 mL/min)",
  // "(구루병 예방목적으로 소아에 투여하는 경우에 한함)")
  if (/NYHA|mmHg|mL\/min|청소율|사구체여과율|GFR|한함|경우/i.test(`${match[1]}${match[2] ?? ""}`)) return false
  // 괄호 설명은 빼고 목록만. 단 "(허혈심장병, 고혈압 포함)"처럼 포함을 밝힌 괄호는 그 항목들도 목록으로 본다
  const included = [...`${match[1]}${match[2] ?? ""}`.matchAll(/\(([^)]*)포함\)/g)].map((found) => found[1])
  const items = [match[1].replace(/\([^)]*\)/g, ""), ...included]
    .join(",")
    .split(/,|·|및|또는|\//)
    .map((item) => compact(item))
  // 사전에 없는 지병은 입력한 말 그대로가 목록 항목일 때만 (예: "부정맥" ↔ "3) 부정맥 환자")
  const names = (condition?.names ?? [name]).map(compact)
  return items.some((item) => names.includes(item))
}

export type ConditionCaution = { medicine: string; line: string; contraindicated: boolean }

/** 지병별로, 고른 약들의 "투여하지 말 것" 항목에서 찾은 줄 */
export function matchConditions(
  conditionsText: string | undefined,
  medicines: { name: string; contraindicatedPatients: string[] }[],
) {
  const result = new Map<string, ConditionCaution[]>()
  for (const [name, condition] of parseConditions(conditionsText)) {
    const found: ConditionCaution[] = []
    for (const medicine of medicines) {
      let scope: string | undefined
      for (const line of medicine.contraindicatedPatients) {
        if (SCOPE.test(line)) {
          scope = line
          continue
        }
        const kind = classify(line, name, condition)
        const shown = scope ? `${line} ${scope}` : line
        const duplicate = found.some((item) => item.medicine === medicine.name && item.line === shown)
        if (kind !== null && !duplicate)
          found.push({ medicine: medicine.name, line: shown, contraindicated: kind && !scope })
      }
    }
    // 투여하지 말 것 먼저
    result.set(name, found.sort((a, b) => Number(b.contraindicated) - Number(a.contraindicated)))
  }
  return result
}
