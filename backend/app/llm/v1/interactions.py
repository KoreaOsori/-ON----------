from itertools import combinations


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
