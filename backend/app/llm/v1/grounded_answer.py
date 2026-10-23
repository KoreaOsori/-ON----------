"""Render verified interaction facts; the model may order blocks, not invent facts."""
import json


def interaction_blocks(payload):
    blocks, seen = [], set()

    def add(text):
        if text and text not in seen:
            seen.add(text)
            blocks.append(text)

    names = {p['product_key']: p['product_name'] for p in payload['products']}
    for check in payload['checks']:
        fact = check['pair_explanation']
        pair = ' ↔ '.join(fact['products'])
        overlap = ', '.join('/'.join(values) for values in fact['same_ingredient_names'])
        add(f"**{' ↔ '.join(fact['products'])}**\n"
            f"- 제품 금기 조회: {fact['product_lookup']}.\n"
            f"- 성분 비교: {fact['ingredient_comparison']}.\n"
            f"- 동일 성분 중복: {overlap + ' — 병용금기와 별도로 확인된 중복이에요' if overlap else '조회된 성분에서는 찾지 못했어요'}.")
        for rule in check['rules']:
            add(f'**{pair} 제품쌍 금기·주의 원문 및 조건**\n' + '\n'.join(
                str(rule[k]) for k in ('prohbt_content', 'remark') if rule.get(k)))
        for rule in check['ingredient_matches']:
            add(f'**{pair} 성분 기준 금기·주의 원문**\n' + '\n'.join(
                str(value) for k in ('contents', 'remarks') for value in (rule.get(k) or []) if value)
                + '\n현재 제품에 적용되는 제형·투여경로·복합제 조건은 별도 확인이 필요해요.')
        for item in check['therapeutic_duplications']:
            add(f"**{pair} 효능군 중복 주의**\n{item['group']}: {', '.join(n for n in item['names'] if n)}. 병용금기와 다른 중복 주의 정보예요.")
    coverage = {}
    for check in payload['checks']:
        coverage.update(check['mapping_coverage'])
    for key, item in coverage.items():
        details = '; '.join(f"{row['name']}: {row['reason']}" for row in item['unmapped_details'])
        add(f"**{names[key]} 성분 확인 범위**\n{item['explanation']}" + (f'\n미연결 이유: {details}.' if details else ''))
    # Quantities are deliberately keyed to ingredient/formulation, never presented
    # as a syrup/tablet product dose without verified formulation applicability.
    for check in payload['checks']:
        for rule in check['daily_dose_limits']:
            add(f"**성분 용량 참고 원문 — 제품 복용량 아님**\n{rule['ingr_name']}: {rule['max_qty']}; "
                f"제형: {rule.get('form_name') or '미확인'}, 투여경로: {rule.get('route') or '미확인'}. "
                '각 제품에 적용되는지 확인되지 않았으며 개인 권장량이나 제품별 상한으로 사용하면 안 돼요.')
    for evidence in payload.get('evidence', []):
        # Whole source text keeps exceptions intact. Never let the model choose
        # an arbitrary short quotation that could omit a qualifier.
        add(f"**{names.get(evidence['product_key'], '제품')} 설명서 참고 원문**\n{evidence['text']}")
    return blocks


def render_interactions(blocks, result):
    order = list(range(len(blocks)))
    if result.get('stop_reason') == 'end_turn':
        try:
            data = json.loads(result['answer'])
            proposed = data['order']
            if (set(data) == {'order'} and isinstance(proposed, list)
                    and all(type(index) is int for index in proposed)
                    and sorted(proposed) == order):
                order = proposed
        except (ValueError, KeyError, TypeError):
            pass
    return ('제품별 조회 결과를 구분해 안내드릴게요. 금기 미발견은 함께 복용해도 안전하다는 뜻이 아니에요.\n\n'
            + '\n\n'.join(blocks[i] for i in order)
            + '\n\n성분 기준 비교는 조회·연결된 범위에 한정되며 제형·투여경로·복합제 적용 조건에 한계가 있어요. '
            '함께 복용할지는 약사나 의사에게 확인해 주세요.')
