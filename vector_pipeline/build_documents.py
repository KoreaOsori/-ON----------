import hashlib
import json

from chunking import CHUNKING_VERSION, normalize, split_text

BUILDER_VERSION = "product-documents-v1"
DRUG_DOCS = {"doc_efficacy": "benefits", "doc_dosage": "usage",
             "doc_precautions": "precautions", "doc_pn": "additional"}
HEALTH_FIELDS = {"rawmtrl_nm": "ingredients", "primary_fnclty": "benefits",
                 "ntk_mthd": "usage", "iftkn_atnt_matr_cn": "precautions",
                 "cstdy_mthd": "storage", "pog_daycnt": "storage"}


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fields_text(row, fields):
    return "\n".join(f"{label}: {normalize(row.get(key))}" for key, label in fields
                     if row.get(key) is not None and normalize(row.get(key)))


def sections(row, kind):
    if kind == "health_food":
        yield "overview", "overview", fields_text(row, [
            ("prdt_shap_cd_nm", "제형"), ("dispos", "성상")])
        for field, section in HEALTH_FIELDS.items():
            yield section, field, normalize(row.get(field))
        return
    yield "overview", "overview", fields_text(row, [
        ("etc_otc_name", "전문/일반"), ("prduct_type", "분류"), ("chart", "성상")])
    yield "ingredients", "ingredients", fields_text(row, [
        ("item_ingr_name", "성분명"), ("material_name", "원료 및 함량 원문")])
    for field, section in DRUG_DOCS.items():
        for index, article in enumerate(row.get(field) or []):
            text = "\n".join(normalize(article.get(k)) for k in
                             ("section_title", "article_title", "text") if normalize(article.get(k)))
            yield section, f"{field}/{index}", text
    for field in ("dur_pregnancy", "dur_elderly", "dur_age", "dur_dosage",
                  "dur_duration", "dur_efficacy_dup", "dur_sr_split"):
        rules = row.get(field) or []
        if isinstance(rules, dict):
            rules = [rules]
        for index, rule in enumerate(rules):
            yield "precautions", f"{field}/{index}", "DUR 유형: " + field + "\n" + json.dumps(
                rule, ensure_ascii=False, default=str, sort_keys=True)
    for field, section in {"efcy": "benefits", "use_method": "usage", "atpn_warn": "precautions",
                           "atpn": "precautions", "intrc": "interactions", "se": "precautions",
                           "deposit_method": "storage"}.items():
        yield section, f"easy_info/{field}", normalize((row.get("easy_info") or {}).get(field))
    yield "storage", "storage_method", normalize(row.get("storage_method"))


def build_documents(row, kind, source, max_chars=1800, overlap=150):
    if kind not in ("drug", "health_food"):
        raise ValueError("지원하지 않는 제품 유형")
    key_field, name_field, maker_field = (("item_seq", "item_name", "entp_name") if kind == "drug"
                                         else ("prdlst_report_no", "prdlst_nm", "bssh_nm"))
    product_id = normalize(row.get(key_field))
    name = normalize(row.get(name_field))
    if not product_id or not name or not row.get("snapshot"):
        raise ValueError(f"필수 제품 ID·제품명·snapshot 누락: {kind}/{product_id}")
    product_key = f"{kind}:{product_id}"
    label = "의약품" if kind == "drug" else "건강기능식품"
    for section, ref, body in sections(row, kind):
        if not body:
            if section != "overview":
                continue
            body = "제품 기본정보"
        prefix = f"제품 종류: {label}\n제품명: {name}\n업체명: {normalize(row.get(maker_field))}\n정보 유형: {section}\n"
        for index, text in enumerate(split_text(body, max_chars, overlap)):
            content = prefix + text
            version = f"{BUILDER_VERSION}:{CHUNKING_VERSION}:{max_chars}:{overlap}"
            yield {
                "chunk_id": digest(f"{product_key}|{ref}|{index}|{version}"),
                "product_type": kind, "source_product_id": product_id,
                "product_key": product_key, "section_type": section,
                "source_ref": ref, "chunk_index": index, "content": content,
                "content_hash": digest(content), "document_version": version,
                "source_s3_key": source, "snapshot": str(row["snapshot"]),
                "sale_status": row.get("sale_status") if kind == "drug" else None,
            }
