"""수집 대상 오퍼레이션 → 서비스명 (01 API 데이터 구조 문서 기준, 총 21개)."""

OPERATIONS = {
    # e약은요
    "getDrbEasyDrugList": "DrbEasyDrugInfoService",
    # 낱알식별
    "getMdcinGrnIdntfcInfoList03": "MdcinGrnIdntfcInfoService03",
    # DUR 성분정보 (끝 번호 02)
    "getCpctyAtentInfoList02": "DURIrdntInfoService03",
    "getEfcyDplctInfoList02": "DURIrdntInfoService03",
    "getMdctnPdAtentInfoList02": "DURIrdntInfoService03",
    "getOdsnAtentInfoList02": "DURIrdntInfoService03",
    "getPwnmTabooInfoList02": "DURIrdntInfoService03",
    "getSpcifyAgrdeTabooInfoList02": "DURIrdntInfoService03",
    "getUsjntTabooInfoList02": "DURIrdntInfoService03",
    # DUR 품목정보 (끝 번호 03)
    "getDurPrdlstInfoList03": "DURPrdlstInfoService03",
    "getCpctyAtentInfoList03": "DURPrdlstInfoService03",
    "getEfcyDplctInfoList03": "DURPrdlstInfoService03",
    "getMdctnPdAtentInfoList03": "DURPrdlstInfoService03",
    "getOdsnAtentInfoList03": "DURPrdlstInfoService03",
    "getPwnmTabooInfoList03": "DURPrdlstInfoService03",
    "getSeobangjeongPartitnAtentInfoList03": "DURPrdlstInfoService03",
    "getSpcifyAgrdeTabooInfoList03": "DURPrdlstInfoService03",
    "getUsjntTabooInfoList03": "DURPrdlstInfoService03",
    # 허가정보
    "getDrugPrdtPrmsnInq08": "DrugPrdtPrmsnInfoService08",
    "getDrugPrdtPrmsnDtlInq08": "DrugPrdtPrmsnInfoService08",
    "getDrugPrdtMcpnDtlInq08": "DrugPrdtPrmsnInfoService08",
}

# 식품안전나라 (openapi.foodsafetykorea.go.kr) — 인증키와 호출 방식이 공공데이터포털과 다르다
FOOD_SAFETY_OPERATIONS = {
    # 건강기능식품 품목제조신고(원재료)
    "C003": "FoodSafetyKorea",
}
