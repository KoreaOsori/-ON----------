"""llm_client.wrap_create: thinking 끄기와 거부 시 한 번 다시 시도."""
import asyncio

from app.llm.v2.config import V2Settings
from app.llm.v2.llm_client import wrap_create


class _Recorder:
    def __init__(self, fail_on_thinking=False):
        self.calls = []
        self._fail = fail_on_thinking

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self._fail and "thinking" in kwargs:
            raise RuntimeError("thinking: Extra inputs are not permitted")
        return "ok"


def test_thinking_disabled_is_sent_with_model_and_limit():
    rec = _Recorder()
    out = asyncio.run(wrap_create(rec, "m", 900, True)(messages=[]))
    assert out == "ok" and rec.calls == [{"model": "m", "max_tokens": 900, "thinking": {"type": "disabled"}, "messages": []}]


def test_thinking_left_alone_when_not_requested():
    rec = _Recorder()
    asyncio.run(wrap_create(rec, "m", 900, False)(messages=[]))
    assert "thinking" not in rec.calls[0]


def test_rejected_thinking_option_is_dropped_once_and_remembered():
    rec = _Recorder(fail_on_thinking=True)
    create = wrap_create(rec, "m", 900, True)

    async def two():
        await create(messages=[])
        await create(messages=[])

    asyncio.run(two())
    assert ["thinking" in c for c in rec.calls] == [True, False, False]


def test_other_errors_are_not_swallowed():
    class Boom:
        async def __call__(self, **kwargs):
            raise RuntimeError("throttled")

    try:
        asyncio.run(wrap_create(Boom(), "m", 900, True)(messages=[]))
        raise AssertionError("예외가 전달되어야 한다")
    except RuntimeError as exc:
        assert str(exc) == "throttled"


def test_settings_default_disables_thinking_and_env_can_enable():
    assert V2Settings.from_env({}).thinking_disabled is True
    assert V2Settings.from_env({"LLM_V2_THINKING": "on"}).thinking_disabled is False
