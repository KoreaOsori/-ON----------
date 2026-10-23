from itertools import combinations


def ingredient_coverage(product, rows):
    """Describe lookup coverage, not clinical safety or label completeness."""
    total = len(rows)
    coded = sum(bool(row['dur_ingr_code']) for row in rows)
    name = product.get('product_name') or '해당 제품'
    if not total:
        state = 'missing'
        explanation = f'{name}: 성분 자료를 찾지 못해 성분별 비교를 진행할 수 없어요.'
    elif not coded:
        state = 'none'
        explanation = f'{name}: 조회된 성분 {total}개 중 병용금기 비교에 연결할 수 있는 성분은 0개예요.'
    elif coded < total:
        state = 'partial'
        explanation = f'{name}: 조회된 성분 {total}개 중 {coded}개만 병용금기 비교에 연결할 수 있어요.'
    else:
        state = 'all_available'
        explanation = f'{name}: 조회된 성분 {total}개 모두 병용금기 비교에 연결할 수 있어요.'
    return {'ingredient_count': total, 'coded_count': coded,
            'unmapped_names': [r.get('ingr_name') or r['ingr_key'] for r in rows if not r['dur_ingr_code']],
            'missing_ingredient_rows': not bool(rows),
            'mapping_state': state, 'explanation': explanation}


def supplemental_cautions(first, second, ac, bc, rules):
    groups, doses = {}, []
    for rule in rules:
        if rule.get('mix_type') != '단일':
            continue
        code = rule['ingr_code']
        if rule['caution_type'] == '효능군중복' and rule.get('sers_name'):
            groups.setdefault(rule['sers_name'], {})[code] = rule.get('ingr_name')
        if rule['caution_type'] == '용량주의' and rule.get('route') != '경구 외':
            for product, codes in ((first, ac), (second, bc)):
                if code in codes and product.get('route') != '경구 외':
                    entry = {'product_key': product['product_key'], 'product_route': product.get('route'),
                             **rule, 'scope': 'ingredient_reference',
                             'applicability': '제형·투여경로 확인 필요. 개인 권장량이나 제품 복용량이 아님'}
                    if entry not in doses:
                        doses.append(entry)
    duplicates = []
    # Only known oral products qualify for a product-level efficacy-group warning.
    oral = first.get('route') == second.get('route') == '경구'
    for group, members in sorted(groups.items()):
        pairs = sorted({tuple(sorted((a, b))) for a in ac & members.keys()
                        for b in bc & members.keys() if a != b})
        if pairs and oral:
            codes = sorted({code for pair in pairs for code in pair})
            duplicates.append({'group': group, 'codes': codes, 'names': [members[c] for c in codes],
                               'verdict': 'duplicate_caution', 'scope': 'single_ingredient_rule',
                               'source': 'gold.dur_ingredient_rule'})
    return {'therapeutic_duplications': duplicates,
            'therapeutic_duplication_result': 'matched' if duplicates else
                'not_checkable' if not oral or not ac or not bc else 'not_found_in_mapped_codes',
            'daily_dose_limits': doses}


def compare_gold(products, ingredients, rules, ingredient_rules=(), dur_rules=()):
    """Gold rows are product-specific: never extrapolate a code pair to other products.

    Codes are compared for provenance, but an exact official product DUR row remains
    valid when ingredient mappings are absent (including composite ingredient codes).
    """
    checks = []
    for first, second in combinations([p for p in products if p["product_type"] == "drug"], 2):
        ak, bk = first["product_key"], second["product_key"]
        aid, bid = ak.split(":", 1)[1], bk.split(":", 1)[1]
        a, b = ingredients.get(ak, []), ingredients.get(bk, [])
        ac = {r["dur_ingr_code"] for r in a if r["dur_ingr_code"]}
        bc = {r["dur_ingr_code"] for r in b if r["dur_ingr_code"]}
        matches, seen = [], set()
        for rule in rules:
            forward = rule["item_seq"] == aid and rule["mixture_item_seq"] == bid
            reverse = rule["item_seq"] == bid and rule["mixture_item_seq"] == aid
            if not (forward or reverse):
                continue
            left, right = (ac, bc) if forward else (bc, ac)
            signature = (rule["basis"], rule["source_key"], rule.get("prohbt_content"), rule.get("remark"),
                         tuple(sorted((rule.get("ingr_code") or "", rule.get("mixture_ingr_code") or ""))))
            if signature in seen:
                continue
            seen.add(signature)
            matches.append({**rule, "code_match": bool(rule.get("ingr_code") in left
                                                     and rule.get("mixture_ingr_code") in right),
                            "source": "gold.drug_contraindication"})
        complete = bool(a and b and all(r["dur_ingr_code"] for r in a + b)
                        and first.get("sale_status") == "판매" and second.get("sale_status") == "판매")
        status = ("contraindicated" if any(r["basis"] == "품목 DUR" for r in matches)
                  else "ingredient_caution" if matches else "not_found" if complete else "unknown")
        ingredient_matches = []
        for rule in ingredient_rules:
            left, right = rule['ingr_code'], rule['mixture_ingr_code']
            # Only cross-product combinations: not two ingredients from one product.
            if (left in ac and right in bc) or (left in bc and right in ac):
                ingredient_matches.append({**rule, 'scope': 'ingredient_only',
                    'verdict': 'ingredient_contraindication' if rule['item_rows'] else 'ingredient_caution',
                    'applicability': '제형·투여경로·복합제 조건은 해당 제품에 적용되는지 별도 확인 필요'})
        coverage = {ak: ingredient_coverage(first, a), bk: ingredient_coverage(second, b)}
        checks.append({"first": ak, "second": bk, "status": status, "coverage_complete": complete,
                       **supplemental_cautions(first, second, ac, bc, dur_rules),
                       "duplicate_ingredient_codes": sorted(ac & bc),
                       "product_pair_result": 'contraindicated' if any(r['basis'] == '품목 DUR' for r in matches)
                           else 'ingredient_caution' if matches else 'not_found',
                       "ingredient_pair_result": 'matched' if ingredient_matches else 'not_found_in_mapped_codes'
                           if ac and bc else 'not_checkable',
                       "ingredient_matches": ingredient_matches, "mapping_coverage": coverage,
                       "rules": matches, "ingredients": {ak: a, bk: b},
                       "duplicate_ingredients": sorted({r["ingr_key"] for r in a} & {r["ingr_key"] for r in b}),
                       "ingredient_sources": ["gold.drug_ingredient"]})
    return checks


def compare(products: list[dict], ingredients: dict, rules: list[dict], rules_complete: bool) -> list[dict]:
    """Compare exact DUR code sets, in both directions, without an LLM.

    A rule side is an ALL-of combination, never an ANY-of list. Conditional rules
    stay conditional; this code does not infer patient/route/dose conditions.
    """
    checks = []
    drugs = [p for p in products if p["product_type"] == "drug"]
    for first, second in combinations(drugs, 2):
        a = ingredients.get(first["product_key"], {})
        b = ingredients.get(second["product_key"], {})
        ac, bc = set(a.get("codes", [])), set(b.get("codes", []))
        matches = []
        for rule in rules:
            left, right = set(rule["left_codes"]), set(rule["right_codes"])
            if left and right and ((left <= ac and right <= bc) or (left <= bc and right <= ac)):
                matches.append(rule)
        complete = bool(rules_complete and a.get("complete") and b.get("complete") and ac and bc)
        status = ("contraindicated" if any(not r["conditions"] for r in matches)
                  else "conditional" if matches else "not_found" if complete else "unknown")
        checks.append({"first": first["product_key"], "second": second["product_key"],
                       "status": status, "coverage_complete": complete, "rules": matches,
                       "ingredient_sources": [a.get("source"), b.get("source")]})
    return checks
