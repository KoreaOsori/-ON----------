"""
대화 세션 보관 (메모리, TTL 10분 — plan.md 3-2).

- 알약: prepare() 결과(_prepared)·마지막 결과·시도 횟수 → 각인 입력·색 선택 후 사진을 다시 처리하지 않고 재검색
- 처방전: decide() 결과(drugs)만. OCR 줄·LLM 입출력은 넣지 않는다 (개인정보, claude.md 1-7)
uvicorn worker 1개라 프로세스 메모리로 충분. 재시작하면 세션은 사라지고 410 으로 안내한다.
"""
import threading
import time
import uuid


class SessionExpired(Exception):
    pass


class SessionStore:
    def __init__(self, ttl_sec=600, max_items=500):
        self.ttl = ttl_sec
        self.max_items = max_items
        self._data = {}
        self._lock = threading.Lock()

    def _purge(self, now):
        for k in [k for k, (exp, _) in self._data.items() if exp < now]:
            del self._data[k]
        # 너무 많이 쌓이면 오래된 것부터 버림 (메모리 4GB 보호)
        while len(self._data) > self.max_items:
            del self._data[min(self._data, key=lambda k: self._data[k][0])]

    def create(self, kind, data):
        sid = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._purge(now)
            self._data[sid] = (now + self.ttl, dict(data, kind=kind))
        return sid

    def get(self, sid, kind):
        now = time.time()
        with self._lock:
            self._purge(now)
            item = self._data.get(sid)
            if item is None or item[1]["kind"] != kind:
                raise SessionExpired(sid)
            # 사용할 때마다 만료 시간 연장 (대화 중 끊기지 않게)
            self._data[sid] = (now + self.ttl, item[1])
            return item[1]

    def __len__(self):
        with self._lock:
            return len(self._data)
