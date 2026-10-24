"""에이전트 실행 한도와 도구 허용 목록 (강의의 harness.py 에 해당).

- Limits : 도구 호출 라운드/횟수/시간 상한. 무한 루프와 비용 폭주를 막는다.
- Budget : 한 번의 answer() 호출 동안의 사용량 추적.
- ALLOWED_TOOLS / assert_allowed_tool : 모델이 이름을 만들어내도 허용 목록 밖이면 실행하지 않는다.
"""
import time
from dataclasses import dataclass

from app.llm.v3.config import V3Settings
from app.llm.v3.contra_tool import CONTRA_TOOL_NAME
from app.llm.v3.tools import TOOL_NAME

ALLOWED_TOOLS = frozenset({TOOL_NAME, CONTRA_TOOL_NAME})


class HarnessError(Exception):
    """하니스 정책 위반(허용되지 않은 도구, 한도 초과)."""


class ToolNotAllowedError(HarnessError):
    pass


class BudgetExceededError(HarnessError):
    pass


@dataclass(frozen=True)
class Limits:
    max_tool_rounds: int = 4  # 모델 호출 → 도구 실행을 한 번 도는 단위
    max_tool_calls: int = 6  # 라운드와 상관없이 도구 호출 총 횟수
    max_seconds: float = 60.0  # 전체 벽시계 시간
    max_question_chars: int = 500

    @classmethod
    def from_settings(cls, settings: V3Settings) -> "Limits":
        return cls(
            max_tool_rounds=max(1, settings.max_tool_rounds),
            max_tool_calls=max(1, settings.max_tool_calls),
            max_seconds=max(1.0, settings.max_seconds),
            max_question_chars=settings.max_question_chars,
        )


class Budget:
    def __init__(self, limits: Limits, clock=time.monotonic) -> None:
        self.limits = limits
        self._clock = clock
        self._started = clock()
        self.rounds = 0
        self.calls = 0

    def elapsed(self) -> float:
        return self._clock() - self._started

    def remaining_seconds(self) -> float:
        return self.limits.max_seconds - self.elapsed()

    def check_time(self) -> None:
        if self.remaining_seconds() <= 0:
            raise BudgetExceededError("시간 한도를 넘었습니다.")

    @property
    def rounds_left(self) -> int:
        return self.limits.max_tool_rounds - self.rounds

    def consume_round(self) -> None:
        if self.rounds >= self.limits.max_tool_rounds:
            raise BudgetExceededError("도구 호출 라운드 한도를 넘었습니다.")
        self.rounds += 1

    def can_call_tool(self) -> bool:
        return self.calls < self.limits.max_tool_calls

    def consume_call(self) -> None:
        if not self.can_call_tool():
            raise BudgetExceededError("도구 호출 횟수 한도를 넘었습니다.")
        self.calls += 1


def assert_allowed_tool(name: str) -> None:
    if name not in ALLOWED_TOOLS:
        raise ToolNotAllowedError(f"허용되지 않은 도구입니다: {name[:40]}")
