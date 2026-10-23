"""Render verified interaction facts; the model may order blocks, not invent facts."""
import json
import re


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
        scope = fact['comparison_scope']
        if scope == 'unavailable':
            missing = [names[key] for key, coverage in check['mapping_coverage'].items()
                       if coverage['missing_ingredient_rows']]
            unlinked = [names[key] for key, coverage in check['mapping_coverage'].items()
                        if not coverage['missing_ingredient_rows'] and not coverage['coded_count']]
            parts = []
            if missing:
                parts.append(f"{', '.join(missing)}의 성분 자료를 찾지 못해 성분끼리 비교하지 못했어요.")
            if unlinked:
                parts.append(f"{', '.join(unlinked)}의 성분은 확인했지만 비교에 필요한 정보가 부족해 성분끼리 비교하지 못했어요.")
            comparison = ' '.join(parts)
        elif scope == 'partial':
            comparison = ('일부 성분만 비교했고, 그 범위에서는 금기 규칙을 찾지 못했어요. 나머지 성분은 확인이 필요해요.'
                          if not check['ingredient_matches'] else '일부 성분에서 금기·주의 규칙을 찾았어요. 적용 조건은 아래를 확인해 주세요.')
        elif scope == 'no_distinct_pairs':
            comparison = '비교 가능한 성분이 서로 같아 동일 성분 중복으로 구분했어요.'
        else:
            comparison = ('조회된 성분끼리 비교한 범위에서도 금기 규칙을 찾지 못했어요.'
                          if not check['ingredient_matches'] else '성분 기준 금기·주의 규칙도 확인됐어요.')
        add(f"**{pair}**\n{fact['product_lookup']}. {comparison}"
            + (f'\n겹치는 성분: {overlap}. 성분 중복은 병용금기와 별개로 주의가 필요해요.' if overlap else ''))
        for rule in check['rules']:
            add(f'**{pair} 제품쌍 금기·주의 원문 및 조건**\n' + '\n'.join(
                str(rule[k]) for k in ('prohbt_content', 'remark') if rule.get(k)))
        for rule in check['ingredient_matches']:
            add(f'**{pair} 성분 기준 금기·주의 원문**\n' + '\n'.join(
                str(value) for k in ('contents', 'remarks') for value in (rule.get(k) or []) if value)
                + '\n현재 제품에 적용되는 제형·투여경로·복합제 조건은 별도 확인이 필요해요.')
        for item in check['therapeutic_duplications']:
            add(f"**{pair} 효능군 중복 주의**\n{item['group']}: {', '.join(n for n in item['names'] if n)}. 병용금기와 다른 중복 주의 정보예요.")
    # Quantities are deliberately keyed to ingredient/formulation, never presented
    # as a syrup/tablet product dose without verified formulation applicability.
    dose_requested = bool(re.search(r'용량|상한|최대|몇\s*(?:정|알|미리|밀리|ml|mg)', payload.get('question', ''), re.I))
    for check in payload['checks'] if dose_requested else []:
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
    return ('함께 복용할 때 확인할 점을 약 조합별로 정리했어요.\n\n'
            + '\n\n'.join(blocks[i] for i in order)
            + '\n\n금기를 찾지 못했다고 안전이 확인된 것은 아니에요. 약의 형태와 복합 성분에 따른 조건도 있어, '
            '함께 드시기 전 약사나 의사에게 확인해 주세요.')
