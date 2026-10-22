from itertools import combinations


def compare_gold(products, ingredients, rules):
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
        checks.append({"first": ak, "second": bk, "status": status, "coverage_complete": complete,
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
