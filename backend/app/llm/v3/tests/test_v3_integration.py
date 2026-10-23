"""V3 regression: real tool path with synthetic Gold rows, no network."""
from app.llm.v3.agent import DrugInfoAgent
from app.llm.v3.config import V3Settings
from app.llm.v3.contra_tool import ContraindicationTool
from app.llm.v3.gold_safety import GoldContraStore, compare_products
from app.llm.v3.harness import Limits
from app.llm.v3.tests.helpers import FakeReader, FakeReaderFactory, ScriptedModel, response, tool_use_block, make_settings
from app.llm.v3.tests.test_contra_tool import _db, CATALOG


def ingredient(seq, key, code):
    return dict(item_seq=seq, ingr_key=key, ingr_name=key, dur_ingr_code=code)


ROWS = [ingredient('100', '공통성분', 'D1'), ingredient('100', '미연결', None),
        ingredient('200', '공통성분', 'D1'), ingredient('200', '다른성분', 'D2'),
        ingredient('300', '미연결성분', None)]


def gold_reader(product_rules=(), ingredient_rules=(), mappings=()):
    def handler(sql, params):
        if 'SELECT item_seq, sale_status, route' in sql:
            return [dict(item_seq=i, sale_status='판매', route='경구') for i in params['ids']]
        if 'gold.drug_ingredient' in sql:
            if 'WHERE ingr_name = :name' in sql:
                return []
            if 'array_agg' in sql:
                return list(mappings)
            return [dict(r) for r in ROWS if r['item_seq'] in params['ids']]
        if 'gold.drug_contraindication' in sql:
            return list(ingredient_rules if 'GROUP BY' in sql else product_rules)
        if 'gold.dur_ingredient_rule' in sql:
            return []
        if 'gold.health_food' in sql:
            return [{'iftkn_atnt_matr_cn': '특정 약을 복용 중이면 전문가와 상담하세요. 예외 조건도 확인하세요.'}]
        return _db(sql, params)
    return FakeReader(handler)


async def test_gold_three_drugs_cover_every_pair_and_separate_missing_codes():
    checks = await compare_products(gold_reader(), CATALOG[:3])
    assert len(checks) == 3
    assert [c['pair_explanation']['comparison_scope'] for c in checks] == ['partial', 'unavailable', 'unavailable']
    assert checks[0]['pair_explanation']['same_ingredient_names'] == [['공통성분']]
    assert not checks[1]['mapping_coverage']['drug:300']['missing_ingredient_rows']
    assert checks[1]['mapping_coverage']['drug:300']['coded_count'] == 0


async def test_official_reverse_product_rule_keeps_conditions_without_codes():
    rule = dict(item_seq='300', mixture_item_seq='100', basis='품목 DUR', source_key='test',
                prohbt_content='시험용 금기 근거', remark='특정 조건에서만 적용', ingr_code='DX', mixture_ingr_code='DY')
    checks = await compare_products(gold_reader([rule]), [CATALOG[0], CATALOG[2]])
    assert checks[0]['status'] == 'contraindicated'
    assert checks[0]['rules'][0]['remark'] == '특정 조건에서만 적용'
    assert checks[0]['pair_explanation']['comparison_scope'] == 'unavailable'


async def test_exact_unique_mapping_only_and_no_fuzzy_code_guess():
    mapping = [dict(ingr_name='미연결', codes=['D3']), dict(ingr_name='미연결성분', codes=['D4', 'D5'])]
    checks = await compare_products(gold_reader(mappings=mapping), CATALOG[:3])
    assert checks[0]['mapping_coverage']['drug:100']['coded_count'] == 2
    assert checks[1]['mapping_coverage']['drug:300']['coded_count'] == 0


async def test_cross_product_ingredient_rule_preserves_reverse_direction_and_conditions():
    rule = dict(ingr_code='D2', mixture_ingr_code='D1', ingr_name='다른성분', mixture_ingr_name='공통성분',
                item_rows=1, rule_rows=0, contents=['성분 기준 시험 근거'], remarks=['적용 조건 원문'])
    checks = await compare_products(gold_reader(ingredient_rules=[rule]), CATALOG[:3])
    assert checks[0]['ingredient_pair_result'] == 'matched'
    assert checks[0]['ingredient_matches'][0]['remarks'] == ['적용 조건 원문']
    assert checks[1]['ingredient_pair_result'] == 'not_checkable'
    assert checks[2]['ingredient_matches'] == []


async def test_approximate_product_identity_note_survives_gold_formatting():
    tool = ContraindicationTool(make_settings(), FakeReaderFactory(gold_reader()), GoldContraStore())
    result = await tool.run({'products': ['와파린정(테스트)', '아스피린장용정100밀리그램']})
    assert not result.is_error and '정확히 일치하는 제품이 없어' in result.text
    assert '와파린정(테스트)' in result.text


async def test_rds_tool_really_uses_python_verdicts_and_food_gold_field():
    reader = gold_reader()
    tool = ContraindicationTool(make_settings(), FakeReaderFactory(reader), GoldContraStore())
    result = await tool.run({'products': ['와파린정', '아스피린장용정100밀리그램', '홍삼정']})
    assert not result.is_error
    assert '[Python 판정 결과]' in result.text and '겹치는 성분: 공통성분' in result.text
    assert '특정 약을 복용 중이면 전문가와 상담하세요. 예외 조건도 확인하세요.' in result.text
    assert any('iftkn_atnt_matr_cn' in sql for sql, _ in reader.calls)
    assert len([e for e in result.evidence if e.section_type == 'interaction_check']) == 1


async def test_drug_food_pair_does_not_run_ingredient_comparison():
    reader = gold_reader()
    result = await ContraindicationTool(make_settings(), FakeReaderFactory(reader), GoldContraStore()).run(
        {'products': ['와파린정', '홍삼정']})
    assert not result.is_error and '예외 조건도 확인하세요' in result.text
    assert not any('gold.drug_ingredient' in sql for sql, _ in reader.calls)


async def test_agent_names_confirmed_ambiguous_and_missing_without_second_model_call():
    tool = ContraindicationTool(make_settings(), FakeReaderFactory(gold_reader()), GoldContraStore())
    model = ScriptedModel(response(tool_use_block('1', 'check_contraindication', products=['와파린정', '타이레놀', '없는약'])))
    # Info tool is not called; both expose the spec required by the model adapter.
    result = await DrugInfoAgent(model, tool, Limits(), contra_tool=tool).run('같이 먹어도 되나요?')
    assert result.stop_reason == 'needs_clarification'
    assert '와파린정은(는) 제품을 확인했어요' in result.answer
    assert '타이레놀정500밀리그램' in result.answer and '없는약' in result.answer
    assert '제조사' in result.answer and len(model.calls) == 1


async def test_caller_products_are_merged_even_if_model_omits_one():
    reader = gold_reader()
    tool = ContraindicationTool(make_settings(), FakeReaderFactory(reader), GoldContraStore())
    model = ScriptedModel(response(tool_use_block('1', 'check_contraindication', products=['와파린정', '타이레놀'])))
    result = await DrugInfoAgent(model, tool, Limits(), contra_tool=tool).run('함께 복용?', products=['없는약'])
    assert '없는약' in result.answer


def test_v3_settings_override_v2_fallback_without_changing_shared_secrets():
    fallback = V3Settings.from_env({'LLM_V2_API_KEY': 'inherited'})
    own = V3Settings.from_env({'LLM_V2_API_KEY': 'inherited', 'LLM_V3_API_KEY': 'own'})
    assert fallback.api_key == 'inherited' and own.api_key == 'own'
    assert own.app_secret_id == 'pill-check/dev/app'


def test_parent_registers_all_versions_and_enters_v3_lifespan():
    import ast
    from pathlib import Path
    source = (Path(__file__).parents[3] / 'main.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    mounts = [n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == 'mount']
    assert mounts == ['/api/llm/v1', '/api/llm/v2', '/api/llm/v3']
    assert 'llm_v3_lifespan(app.state.llm_v3_app)' in source
