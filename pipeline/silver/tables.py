"""원본 오퍼레이션별 정리 명세 (docs/silver_table_spec.md 의 코드 버전).

여기 Table 은 API 오퍼레이션 하나를 정리한 결과다. 대부분은 build.py 가 drug_product 로 합치는 재료로만 쓰고,
병용금기 2개는 dur_contraindication 하나로 합치고, 건강기능식품은 그대로 silver 테이블이 된다 (OUTPUT_TABLES).
컬럼 순서·이름·타입·필수 여부를 여기서 고정한다. 바꾸면 SPEC_VERSION 을 올리고 명세 문서도 같이 고친다.
rule_key 정체성 컬럼은 바꾸면 모든 키가 바뀌므로 RAG팀에 미리 알린다.
"""

import re
from dataclasses import dataclass, field

SPEC_VERSION = "0.2"


@dataclass(frozen=True)
class Col:
    name: str
    type: str = "str"  # str / int / float / date / bool / list
    src: str | None = None  # 원본 컬럼. None 이면 build.py 가 계산하는 파생 컬럼
    parse: str | None = None  # date / int / float / comma / codes / bracket_code / bracket_name / last_path / collected
    required: bool = False


def snake(name):
    if any(c.islower() for c in name):
        name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return name.lower()


PARSE_TYPES = {"date": "date", "int": "int", "float": "float", "comma": "list", "codes": "list", "collected": "list"}


def S(src, name=None, parse=None, required=False):
    return Col(name or snake(src), PARSE_TYPES.get(parse, "str"), src, parse, required)


def R(src, name=None, parse=None):
    return S(src, name, parse, required=True)


def codes(src, name=None):
    return S(src, (name or snake(src)) + "_codes", parse="codes")


def derived(name, type, required=True):
    return Col(name, type, None, None, required)


@dataclass
class Table:
    name: str
    operation: str
    columns: list
    primary_key: tuple
    ignore_source: tuple = ()  # 원본에 있지만 이 테이블 컬럼으로 쓰지 않는 것
    exclude_when_all_null: tuple = ()  # 이 원본 컬럼이 모두 null 인 행은 제외
    collapse_key: tuple = ()  # 원본 컬럼 기준으로 이 키가 같은 행을 1행으로 합침
    resolve: dict = field(default_factory=dict)  # 합칠 때 값이 달라도 되는 원본 컬럼 → 우선값 (None 이면 null 아닌 값 우선)
    rule_key: tuple = ()  # rule_key 정체성 (원본 컬럼, 순서 고정)
    same_as: tuple = ()  # (원본 컬럼, 같아야 하는 원본 컬럼) — 검사 후 버림


# ---------------------------------------------------------------- 허가 정보

PERMIT_ITEM = Table(
    "permit_item", "getDrugPrdtPrmsnInq08",
    [
        R("ITEM_SEQ"), R("ITEM_NAME"), S("ITEM_ENG_NAME"), S("ENTP_NAME"), S("ENTP_ENG_NAME"), S("ENTP_SEQ"),
        S("ENTP_NO"), S("ITEM_PERMIT_DATE", parse="date"), S("INDUTY"), S("PRDLST_STDR_CODE"),
        R("SPCLTY_PBLC", "etc_otc_name"), S("PRDUCT_TYPE"), codes("PRDUCT_TYPE"), S("PRDUCT_PRMISN_NO"),
        S("ITEM_INGR_NAME"), S("ITEM_INGR_CNT", parse="int"), S("BIG_PRDT_IMG_URL"), S("PERMIT_KIND_CODE"),
        S("CANCEL_DATE", parse="date"), R("CANCEL_NAME"), S("EDI_CODE", parse="comma"), S("BIZRNO"),
        derived("is_active", "bool"),
    ],
    ("item_seq",),
)

DOC_SOURCE_COLUMNS = {"EE_DOC_DATA": "EE", "UD_DOC_DATA": "UD", "NB_DOC_DATA": "NB", "PN_DOC_DATA": "PN"}

PERMIT_DETAIL = Table(
    "permit_detail", "getDrugPrdtPrmsnDtlInq08",
    [
        R("ITEM_SEQ"), R("ITEM_NAME"), S("ITEM_ENG_NAME"), S("ENTP_NAME"), S("ENTP_ENG_NAME"), S("ENTP_NO"),
        S("ITEM_PERMIT_DATE", parse="date"), S("CNSGN_MANUF"), R("ETC_OTC_CODE", "etc_otc_name"), S("CHART"),
        S("BAR_CODE", parse="comma"), S("MATERIAL_NAME"), S("EE_DOC_ID"), S("UD_DOC_ID"), S("NB_DOC_ID"),
        S("INSERT_FILE"), S("STORAGE_METHOD"), S("VALID_TERM"), S("REEXAM_TARGET"), S("REEXAM_DATE"),
        S("PACK_UNIT"), S("EDI_CODE", parse="comma"), S("PERMIT_KIND_NAME"), S("MAKE_MATERIAL_FLAG"),
        S("NEWDRUG_CLASS_NAME"), S("INDUTY_TYPE"), S("CANCEL_DATE", parse="date"), R("CANCEL_NAME"),
        S("CHANGE_DATE", parse="date"), S("NARCOTIC_KIND_CODE"), S("GBN_NAME"), S("TOTAL_CONTENT"),
        S("MAIN_ITEM_INGR"), codes("MAIN_ITEM_INGR"), S("INGR_NAME", "additive_ingr"),
        codes("INGR_NAME", "additive_ingr"), S("ATC_CODE"), S("MAIN_INGR_ENG"), S("BIZRNO"), S("RARE_DRUG_YN"),
        S("DATA_PROTECT_START_DATE", parse="date"), S("DATA_PROTECT_END_DATE", parse="date"),
        derived("is_active", "bool"),
    ],
    ("item_seq",),
    ignore_source=tuple(DOC_SOURCE_COLUMNS),
)

PERMIT_INGREDIENT = Table(
    "permit_ingredient", "getDrugPrdtMcpnDtlInq08",
    [
        R("ITEM_SEQ"), R("TAMT_SEQ", parse="int"), R("MTRAL_SN", parse="int"), R("MTRAL_CODE"), S("MTRAL_NM"),
        S("QNT", parse="float"), S("QNT", "qnt_text"), S("INGD_UNIT_CD"), S("CPNT_CTNT_CONT"),
        S("PRDUCT", "item_name"), S("ENTRPS", "entp_name"), S("ENTRPS_PRMISN_NO"), S("MAIN_INGR_ENG"),
        S("BIZRNO"),
    ],
    ("item_seq", "tamt_seq", "mtral_sn"),
    exclude_when_all_null=("MTRAL_SN", "MTRAL_CODE", "TAMT_SEQ"),
)

# ---------------------------------------------------------------- e약은요

EASY_TEXT_FIELDS = {
    "efcyQesitm": "efcy", "useMethodQesitm": "use_method", "atpnWarnQesitm": "atpn_warn", "atpnQesitm": "atpn",
    "intrcQesitm": "intrc", "seQesitm": "se", "depositMethodQesitm": "deposit_method",
}

EASY_DRUG = Table(
    "easy_drug", "getDrbEasyDrugList",
    [
        R("itemSeq"), R("itemName"), S("entpName"), S("openDe", "open_date", parse="date"),
        S("updateDe", "update_date", parse="date"), S("itemImage", "item_images", parse="collected"), S("bizrno"),
    ],
    ("item_seq",),
    ignore_source=tuple(EASY_TEXT_FIELDS),
    collapse_key=("itemSeq",),
)

# ---------------------------------------------------------------- 낱알식별

PILL_IDENTIFICATION = Table(
    "pill_identification", "getMdcinGrnIdntfcInfoList03",
    [
        R("ITEM_SEQ"), R("ITEM_IMAGE", "image_id", parse="last_path"), R("ITEM_IMAGE"), R("ITEM_NAME"),
        S("ITEM_ENG_NAME"), S("ENTP_SEQ"), S("ENTP_NAME"), S("CHART"), S("PRINT_FRONT"), S("PRINT_BACK"),
        S("DRUG_SHAPE"), S("COLOR_CLASS1"), S("COLOR_CLASS2"), S("LINE_FRONT"), S("LINE_BACK"),
        S("LENG_LONG", parse="float"), S("LENG_SHORT", parse="float"), S("THICK", parse="float"),
        S("IMG_REGIST_TS", parse="date"), S("CLASS_NO", "class_code"), S("CLASS_NAME"), S("ETC_OTC_NAME"),
        S("ITEM_PERMIT_DATE", parse="date"), S("FORM_CODE_NAME"), S("MARK_CODE_FRONT_ANAL"),
        S("MARK_CODE_BACK_ANAL"), S("MARK_CODE_FRONT_IMG"), S("MARK_CODE_BACK_IMG"), S("MARK_CODE_FRONT"),
        S("MARK_CODE_BACK"), S("CHANGE_DATE", parse="date"), S("EDI_CODE", parse="comma"),
        S("STD_CD", parse="comma"), S("BIZRNO"),
    ],
    ("item_seq", "image_id"),
)

# ---------------------------------------------------------------- DUR 품목 마스터

DUR_ITEM_MASTER = Table(
    "dur_item_master", "getDurPrdlstInfoList03",
    [
        R("ITEM_SEQ"), R("ITEM_NAME"), S("ENTP_NAME"), S("ITEM_PERMIT_DATE", parse="date"),
        R("ETC_OTC_CODE", "etc_otc_name"), S("CLASS_NO", "class_code", parse="bracket_code"),
        S("CLASS_NO", "class_name", parse="bracket_name"), S("CHART"), S("BAR_CODE", parse="comma"),
        S("MATERIAL_NAME"), S("EE_DOC_ID"), S("UD_DOC_ID"), S("NB_DOC_ID"), S("INSERT_FILE"), S("STORAGE_METHOD"),
        S("VALID_TERM"), S("REEXAM_TARGET"), S("REEXAM_DATE"), S("PACK_UNIT"), S("EDI_CODE", parse="comma"),
        S("CANCEL_DATE", parse="date"), S("CANCEL_NAME"), S("TYPE_CODE", parse="comma"),
        S("TYPE_NAME", parse="comma"), S("CHANGE_DATE", parse="date"), S("BIZRNO"),
    ],
    ("item_seq",),
)


# ---------------------------------------------------------------- DUR 성분 규칙 (6종)

def dur_ingr(name, operation, extra, has_class=True, has_form=True):
    columns = [
        R("DUR_SEQ"), R("TYPE_NAME"), R("MIX_TYPE"), R("INGR_CODE"), S("INGR_ENG_NAME"), S("INGR_NAME"),
        S("MIX_INGR"), codes("MIX_INGR"), S("ORI_INGR"), codes("ORI_INGR"),
    ]
    if has_class:
        columns += [S("CLASS_NAME"), codes("CLASS_NAME")]
    if has_form:
        columns += [S("FORM_NAME")]
    columns += extra
    columns += [
        R("NOTIFICATION_DATE", parse="date"), S("PROHBT_CONTENT"), S("REMARK"), R("DEL_YN"),
        derived("is_rule_valid", "bool"),
    ]
    return Table(name, operation, columns, ("dur_seq",))


DUR_INGR_TABLES = [
    dur_ingr("dur_ingr_cpcty", "getCpctyAtentInfoList02", [S("MAX_QTY")]),
    dur_ingr("dur_ingr_efcy_dplct", "getEfcyDplctInfoList02", [S("EFFECT_CODE"), S("SERS_NAME")], has_form=False),
    dur_ingr("dur_ingr_mdctn_pd", "getMdctnPdAtentInfoList02", [S("MAX_DOSAGE_TERM")]),
    dur_ingr("dur_ingr_odsn", "getOdsnAtentInfoList02", [], has_class=False),
    dur_ingr("dur_ingr_pwnm", "getPwnmTabooInfoList02", [S("GRADE")]),
    dur_ingr("dur_ingr_spcify_agrde", "getSpcifyAgrdeTabooInfoList02", [S("AGE_BASE")]),
]

USJNT_INGR_IDENTITY = (
    "INGR_CODE", "MIX", "ORI", "MIXTURE_INGR_CODE", "MIXTURE_MIX", "MIXTURE_ORI", "PROHBT_CONTENT", "REMARK",
    "NOTIFICATION_DATE",
)

DUR_INGR_USJNT = Table(
    "dur_ingr_usjnt", "getUsjntTabooInfoList02",
    [
        derived("rule_key", "str"), R("INGR_CODE"), S("INGR_ENG_NAME"), S("INGR_KOR_NAME", "ingr_name"),
        R("MIX_TYPE"), S("MIX", "mix_ingr"), codes("MIX", "mix_ingr"), S("ORI"), codes("ORI"),
        S("CLASS", "class_name"), codes("CLASS", "class_name"), R("MIXTURE_INGR_CODE"),
        S("MIXTURE_INGR_ENG_NAME"), S("MIXTURE_INGR_KOR_NAME", "mixture_ingr_name"), R("MIXTURE_MIX_TYPE"),
        S("MIXTURE_MIX", "mixture_mix_ingr"), codes("MIXTURE_MIX", "mixture_mix_ingr"), S("MIXTURE_ORI"),
        codes("MIXTURE_ORI"), S("MIXTURE_CLASS", "mixture_class_name"),
        codes("MIXTURE_CLASS", "mixture_class_name"), R("TYPE_NAME"), R("NOTIFICATION_DATE", parse="date"),
        S("PROHBT_CONTENT"), S("REMARK"), R("DEL_YN"), derived("is_rule_valid", "bool"),
        derived("pair_key", "str"),
    ],
    ("rule_key",),
    collapse_key=USJNT_INGR_IDENTITY,
    resolve={"DEL_YN": "정상", "MIXTURE_CLASS": None},
    rule_key=USJNT_INGR_IDENTITY,
)


# ---------------------------------------------------------------- DUR 품목 규칙

ITEM_CAUTION_IDENTITY = ("ITEM_SEQ", "INGR_CODE", "MIX_INGR", "PROHBT_CONTENT", "REMARK", "NOTIFICATION_DATE")


def dur_item_caution(name, operation, with_rule_key=True):
    columns = [
        R("ITEM_SEQ"), R("ITEM_NAME"), S("ITEM_PERMIT_DATE", parse="date"), S("ENTP_NAME"), S("CHART"),
        S("CLASS_CODE"), S("CLASS_NAME"), R("ETC_OTC_NAME"), S("MAIN_INGR"), codes("MAIN_INGR"), R("TYPE_NAME"),
        R("MIX_TYPE"), R("INGR_CODE"), S("INGR_ENG_NAME"), S("INGR_NAME"), S("INGR_ENG_NAME_FULL"),
        S("MIX_INGR"), codes("MIX_INGR"), S("FORM_NAME"), R("NOTIFICATION_DATE", parse="date"),
        S("PROHBT_CONTENT"), S("REMARK"), S("CHANGE_DATE", parse="date"),
    ]
    if with_rule_key:
        return Table(name, operation, [derived("rule_key", "str")] + columns, ("rule_key",),
                     rule_key=ITEM_CAUTION_IDENTITY)
    return Table(name, operation, columns, ("item_seq", "ingr_code"))


DUR_ITEM_CAUTION_TABLES = [
    dur_item_caution("dur_item_cpcty", "getCpctyAtentInfoList03"),
    dur_item_caution("dur_item_pwnm", "getPwnmTabooInfoList03"),
    dur_item_caution("dur_item_spcify_agrde", "getSpcifyAgrdeTabooInfoList03"),
    dur_item_caution("dur_item_mdctn_pd", "getMdctnPdAtentInfoList03"),
    dur_item_caution("dur_item_odsn", "getOdsnAtentInfoList03", with_rule_key=False),
]

DUR_ITEM_EFCY_DPLCT = Table(
    "dur_item_efcy_dplct", "getEfcyDplctInfoList03",
    [
        R("DUR_SEQ"), R("ITEM_SEQ"), R("ITEM_NAME"), S("ITEM_PERMIT_DATE", parse="date"), S("ENTP_NAME"),
        S("CHART"), S("FORM_CODE"), S("FORM_NAME"), S("FORM_CODE_NAME"), S("ETC_OTC_CODE"), R("ETC_OTC_NAME"),
        S("CLASS_CODE"), S("CLASS_NAME"), S("MAIN_INGR"), codes("MAIN_INGR"), R("TYPE_NAME"), R("EFFECT_NAME"),
        S("SERS_NAME"), R("INGR_CODE"), S("INGR_NAME", "ingr_names", parse="collected"),
        S("INGR_ENG_NAME", "ingr_eng_names", parse="collected"),
        S("INGR_ENG_NAME_FULL", "ingr_eng_name_fulls", parse="collected"), R("MIX", "mix_type"), S("MIX_INGR"),
        codes("MIX_INGR"), R("NOTIFICATION_DATE", parse="date"), S("PROHBT_CONTENT"), S("REMARK"),
        S("CHANGE_DATE", parse="date"), S("BIZRNO"),
    ],
    ("dur_seq", "item_seq"),
    collapse_key=("DUR_SEQ", "ITEM_SEQ"),
)

DUR_ITEM_SEOBANGJEONG = Table(
    "dur_item_seobangjeong", "getSeobangjeongPartitnAtentInfoList03",
    [
        R("ITEM_SEQ"), R("ITEM_NAME"), S("ITEM_PERMIT_DATE", parse="date"), S("FORM_CODE_NAME"), S("ENTP_NAME"),
        S("CHART"), S("CLASS_CODE"), S("CLASS_NAME"), R("ETC_OTC_NAME"), R("MIX", "mix_type"), S("MAIN_INGR"),
        codes("MAIN_INGR"), R("TYPE_NAME"), R("PROHBT_CONTENT"), S("REMARK"), S("CHANGE_DATE", parse="date"),
        S("BIZRNO"),
    ],
    ("item_seq",),
)

DUR_ITEM_USJNT = Table(
    "dur_item_usjnt", "getUsjntTabooInfoList03",
    [
        R("DUR_SEQ"), R("ITEM_SEQ"), R("MIXTURE_ITEM_SEQ"), R("TYPE_CODE"), R("TYPE_NAME"), R("INGR_CODE"),
        S("INGR_KOR_NAME", "ingr_names", parse="collected"), S("INGR_ENG_NAME", "ingr_eng_names", parse="collected"),
        R("MIX", "mix_type"), S("MIX_INGR"), codes("MIX_INGR"), S("ITEM_NAME"), S("ENTP_NAME"), S("CHART"),
        S("FORM_CODE"), S("FORM_NAME"), S("ETC_OTC_CODE"), S("ETC_OTC_NAME"), S("CLASS_CODE"), S("CLASS_NAME"),
        S("MAIN_INGR"), codes("MAIN_INGR"), S("ITEM_PERMIT_DATE", parse="date"), S("CHANGE_DATE", parse="date"),
        R("MIXTURE_INGR_CODE"), S("MIXTURE_INGR_KOR_NAME", "mixture_ingr_names", parse="collected"),
        S("MIXTURE_INGR_ENG_NAME", "mixture_ingr_eng_names", parse="collected"), R("MIXTURE_MIX", "mixture_mix_type"),
        S("MIXTURE_ITEM_NAME"), S("MIXTURE_ENTP_NAME"), S("MIXTURE_CHART"), S("MIXTURE_FORM_CODE"),
        S("MIXTURE_FORM_NAME"), S("MIXTURE_ETC_OTC_CODE"), S("MIXTURE_ETC_OTC_NAME"), S("MIXTURE_CLASS_CODE"),
        S("MIXTURE_CLASS_NAME"), S("MIXTURE_MAIN_INGR"), codes("MIXTURE_MAIN_INGR"),
        S("MIXTURE_ITEM_PERMIT_DATE", parse="date"), S("MIXTURE_CHANGE_DATE", parse="date"),
        R("NOTIFICATION_DATE", parse="date"), S("PROHBT_CONTENT"), S("REMARK"), S("BIZRNO"),
    ],
    ("dur_seq", "item_seq", "mixture_item_seq"),
    collapse_key=("DUR_SEQ", "ITEM_SEQ", "MIXTURE_ITEM_SEQ"),
    same_as=("MIXTURE_DUR_SEQ", "DUR_SEQ"),
)

# ---------------------------------------------------------------- 건강기능식품 (식품안전나라)

HEALTH_FOOD_PRODUCT = Table(
    "health_food_product", "C003",
    [
        R("PRDLST_REPORT_NO"), R("PRDLST_NM"), S("BSSH_NM"), S("LCNS_NO"), S("PRMS_DT", "permit_date", parse="date"),
        S("PRDT_SHAP_CD_NM"), S("SHAP"), S("DISPOS"), S("PRIMARY_FNCLTY"), S("NTK_MTHD"),
        S("IFTKN_ATNT_MATR_CN"), S("CSTDY_MTHD"), S("POG_DAYCNT"), S("STDR_STND"), S("RAWMTRL_NM"),
        S("CRET_DTM", "create_date", parse="date"), S("LAST_UPDT_DTM", "last_update_date", parse="date"),
    ],
    ("prdlst_report_no",),
)

# silver 에 그대로 저장되는 테이블
OUTPUT_TABLES = [HEALTH_FOOD_PRODUCT]
DRUG_PRODUCT_TABLE = "drug_product"
CONTRAINDICATION_TABLE = "dur_contraindication"  # 성분 병용금기 + 품목 병용금기 (level 컬럼으로 구분)
ALL_TABLE_NAMES = [DRUG_PRODUCT_TABLE, CONTRAINDICATION_TABLE] + [t.name for t in OUTPUT_TABLES]
