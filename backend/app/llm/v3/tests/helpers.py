"""테스트 공용 가짜 객체. pytest 없이도(python 직접 실행) 쓸 수 있게 표준 라이브러리만 사용한다."""
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Callable

from app.llm.v3.config import V3Settings


@contextmanager
def raises(exc_type):
    """pytest.raises 의 최소 대체. 예외 객체를 .value 로 돌려준다."""
    holder = SimpleNamespace(value=None)
    try:
        yield holder
    except exc_type as exc:
        holder.value = exc
    else:
        raise AssertionError(f"{exc_type.__name__} 예외가 발생해야 합니다.")


def make_settings(**overrides: Any) -> V3Settings:
    base = dict(
        region="us-east-1", db_host="db.invalid", db_name="pill", db_user="reader", db_password="pw-for-tests",
        llm_model_id="test-model",
    )
    base.update(overrides)
    return V3Settings(**base)


class FakeReader:
    """Reader 가짜: 호출된 (sql, params) 를 기록하고 handler(sql, params) 결과를 돌려준다."""

    def __init__(self, handler: Callable[[str, dict], list[dict]]) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._handler = handler

    async def fetch(self, sql, params=None):
        params = dict(params or {})
        self.calls.append((sql, params))
        return self._handler(sql, params)


class FakeReaderFactory:
    def __init__(self, reader: FakeReader) -> None:
        self.reader = reader
        self.opened = 0

    def __call__(self):
        factory = self

        class _Ctx:
            async def __aenter__(self_inner):
                factory.opened += 1
                return factory.reader

            async def __aexit__(self_inner, *exc):
                return None

        return _Ctx()


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_use_block(tool_id: str, name: str, **arguments: Any) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=arguments)


def response(*blocks: Any, stop_reason: str | None = None) -> SimpleNamespace:
    if stop_reason is None:
        stop_reason = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


class ScriptedModel:
    """create_message 가짜: 호출마다 미리 정한 응답(또는 예외)을 순서대로 돌려준다. 요청은 calls 에 기록."""

    def __init__(self, *script: Any, delay: float = 0.0) -> None:
        self._script = list(script)
        self.calls: list[dict] = []
        self._delay = delay

    async def __call__(self, **kwargs: Any):
        import asyncio
        import copy

        self.calls.append(copy.deepcopy(kwargs))
        if self._delay:
            await asyncio.sleep(self._delay)
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
