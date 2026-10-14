import hashlib

from chunking import normalize, pack_articles, split_text

BUILDER_VERSION = "product-documents-v2.1"
DRUG_DOCS = {"doc_efficacy": "benefits", "doc_dosage": "usage",
             "doc_precautions": "precautions", "doc_pn": "additional"}
HEALTH_FIELDS = {"rawmtrl_nm": "ingredients", "primary_fnclty": "benefits",
                 "ntk_mthd": "usage", "iftkn_atnt_matr_cn": "precautions",
                 "cstdy_mthd": "storage", "pog_daycnt": "storage"}
DUR_LABELS = {"dur_pregnancy": "임부", "dur_elderly": "노인", "dur_age": "연령",
              "dur_dosage": "용량", "dur_duration": "투여기간",
              "dur_efficacy_dup": "효능군 중복", "dur_sr_split": "서방정 분할"}
HUMAN_CONDITIONS = [("ingr_name", "성분"), ("ingr_names", "성분"),
                    ("ingr_eng_name", "성분 영문명"), ("form_name", "제형"),
                    ("form_code_name", "제형명"), ("effect_name", "효능군"),
                    ("sers_name", "계열"), ("grade", "등급"), ("age_base", "연령 기준"),
                    ("max_qty", "최대 용량"), ("max_dosage_term", "최대 투여기간")]
INTERNAL_KEYS = ("rule_key", "dur_seq", "ingr_code", "mix_type", "mix_ingr", "mix_ingr_codes",
                 "link_status", "link_method", "form_code", "effect_code", "notification_date", "change_date")


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def readable(value):
    if isinstance(value, list):
        return ", ".join(normalize(v) for v in value if normalize(v))
    return normalize(value)


def fields_text(row, fields):
    return "\n".join(f"{label}: {readable(row.get(key))}" for key, label in fields if readable(row.get(key)))


def rule_metadata(rule):
    return {k: str(rule[k]) if hasattr(rule[k], "isoformat") else rule[k]
            for k in INTERNAL_KEYS if rule.get(k) is not None}


class DurConditionError(ValueError):
    pass


def dur_blocks(row, max_chars, overlap, on_reject=None):
    """Each alternative is isolated. Conditions repeat on every continuation chunk."""
    for field, label in DUR_LABELS.items():
        rules = row.get(field) or []
        if isinstance(rules, dict):
            rules = [rules]
        for i, parent in enumerate(rules):
            children = parent.get("ingredient_rules") or [None]
            for j, child in enumerate(children):
                child = child or {}
                context_lines = [f"DUR 주의 유형: {label}"]
                for scope, rule in (("제품 규칙", parent), ("성분 규칙", child)):
                    conditions = fields_text(rule, HUMAN_CONDITIONS)
                    if conditions:
                        context_lines.append(f"{scope} 조건:\n{conditions}")
                context = "\n".join(context_lines)
                descriptions = []
                for scope, rule in (("제품 규칙", parent), ("성분 규칙", child)):
                    body = fields_text(rule, [("prohbt_content", "주의내용"), ("remark", "비고")])
                    if body:
                        descriptions.append(f"{scope}:\n{body}")
                body = "\n".join(descriptions)
                budget = max_chars - len(context) - 1
                ref = f"{field}/{i}" + (f"/ingredient_rules/{j}" if parent.get("ingredient_rules") else "")
                metadata = {"parent": rule_metadata(parent), "ingredient_rule": rule_metadata(child)}
                # split_text requires overlap < floor(budget / 2), so 301/150 is invalid.
                if (body and budget < max(100, 2 * (overlap + 1))) or len(context) > max_chars:
                    error = DurConditionError(f"DUR 조건 초과: {ref}, 남은 본문 예산={budget}, 최소={max(100, 2 * (overlap + 1))}")
                    if on_reject is None:
                        raise error
                    on_reject({"source_ref": ref, "error_type": type(error).__name__, "reason": str(error),
                               "context": context, "body": body, "metadata": metadata})
                    continue
                parts = split_text(body, budget, overlap) if body else [""]
                for part in parts:
                    yield "precautions", [ref], context + ("\n" + part if part else ""), metadata


def blocks(row, kind, max_chars, overlap, min_chars, on_reject=None):
    if kind == "health_food":
        yield "overview", ["overview"], fields_text(row, [("prdt_shap_cd_nm", "제형"), ("dispos", "성상")]), {}
        for field, section in HEALTH_FIELDS.items():
            for part in split_text(row.get(field), max_chars, overlap):
                yield section, [field], part, {}
        return
    yield "overview", ["overview"], fields_text(row, [
        ("etc_otc_name", "전문/일반"), ("prduct_type", "분류"), ("chart", "성상")]), {}
    ingredients = fields_text(row, [("item_ingr_name", "성분명"), ("material_name", "원료 및 함량 원문")])
    for part in split_text(ingredients, max_chars, overlap):
        yield "ingredients", ["ingredients"], part, {}
    for field, section in DRUG_DOCS.items():
        articles = []
        for index, article in enumerate(row.get(field) or []):
            text = "\n".join(normalize(article.get(k)) for k in ("section_title", "article_title", "text")
                             if normalize(article.get(k)))
            if text:
                articles.append((f"{field}/{index}", text))
        for refs, text in pack_articles(articles, max_chars, overlap, min_chars):
            yield section, refs, text, {}
    yield from dur_blocks(row, max_chars, overlap, on_reject)
    for field, section in {"efcy": "benefits", "use_method": "usage", "atpn_warn": "precautions",
                           "atpn": "precautions", "intrc": "interactions", "se": "precautions",
                           "deposit_method": "storage"}.items():
        for part in split_text((row.get("easy_info") or {}).get(field), max_chars, overlap):
            yield section, [f"easy_info/{field}"], part, {}
    for part in split_text(row.get("storage_method"), max_chars, overlap):
        yield "storage", ["storage_method"], part, {}


def build_documents(row, kind, source, max_chars=1800, overlap=150, min_chars=900, on_reject=None):
    if kind not in ("drug", "health_food"):
        raise ValueError("지원하지 않는 제품 유형")
    key, name_key, maker_key = (("item_seq", "item_name", "entp_name") if kind == "drug"
                                else ("prdlst_report_no", "prdlst_nm", "bssh_nm"))
    product_id, name, maker = normalize(row.get(key)), normalize(row.get(name_key)), normalize(row.get(maker_key))
    if not product_id or not name or not row.get("snapshot"):
        raise ValueError(f"필수 제품 ID·제품명·snapshot 누락: {kind}/{product_id}")
    product_key = f"{kind}:{product_id}"
    label = "의약품" if kind == "drug" else "건강기능식품"
    version = f"{BUILDER_VERSION}:{max_chars}:{overlap}:{min_chars}"
    for index, (section, refs, body, metadata) in enumerate(blocks(row, kind, max_chars, overlap, min_chars, on_reject)):
        if section == "overview":
            body = f"제품명: {name}\n업체명: {maker}\n{body}".strip()
        content = f"제품 종류: {label}\n정보 유형: {section}\n{body}"
        yield {
            "chunk_id": digest(f"{product_key}|{index}|{version}"),
            "product_type": kind, "source_product_id": product_id, "product_key": product_key,
            "product_name": name, "manufacturer": maker, "section_type": section,
            "source_refs": refs, "metadata": metadata, "chunk_index": index,
            "content": content, "content_hash": digest(content), "document_version": version,
            "source_s3_key": source, "snapshot": str(row["snapshot"]),
            "sale_status": row.get("sale_status") if kind == "drug" else None,
        }
