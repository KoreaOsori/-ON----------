from datetime import datetime

import pytest

from app.integrations import public_data
from app.modules.pharmacies.service import KST, _hours_text, open_status


async def test_health(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_search_medicines_by_category(client):
    response = await client.get("/api/v1/medicines", params={"category": "감기약"})
    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["라마바정"]


async def test_medicine_detail_uses_camel_case(client):
    response = await client.get("/api/v1/medicines/mock-0")
    assert response.status_code == 200
    assert "interactionSummary" in response.json()


async def test_interaction_check_flags_demo_pair(client):
    response = await client.post(
        "/api/v1/interactions/check", json={"medicineIds": ["mock-0", "mock-1", "mock-4"]}
    )
    pairs = response.json()["pairs"]
    assert len(pairs) == 3
    flagged = [pair for pair in pairs if pair["contraindicated"]]
    assert [(pair["first"], pair["second"], pair["level"]) for pair in flagged] == [
        ("가나다정", "마바사정", "금기")
    ]
    assert flagged[0]["details"][0]["basis"] == "품목 DUR"


async def test_interaction_check_requires_two_medicines(client):
    response = await client.post("/api/v1/interactions/check", json={"medicineIds": ["mock-0"]})
    assert response.status_code == 422


async def test_guest_chat_quota(client):
    first = await client.post("/api/v1/chat", json={"question": "가나다정에 대해 알려주세요"})
    assert first.status_code == 200
    assert first.json()["drug"] == "가나다정"
    assert first.json()["remaining"] == 1

    second = await client.post("/api/v1/chat", json={"question": "호흡이 힘들어요"})
    assert second.json()["emergency"] is True
    assert second.json()["remaining"] == 0

    third = await client.post("/api/v1/chat", json={"question": "라마바정은요?"})
    assert third.status_code == 429


async def test_pharmacies_open_only(client, monkeypatch):
    async def fake_near(*, lat, lng, rows=30):
        common = {"dutyAddr": "서울", "dutyTel1": "02-000-0000", "latitude": lat, "longitude": lng}
        return [
            {**common, "hpid": "C2", "dutyName": "닫은약국", "distance": 0.2},
            {
                **common,
                "hpid": "C1",
                "dutyName": "24시약국",
                "distance": 0.05,
                "startTime": "0000",
                "endTime": 2400,
            },
        ]

    monkeypatch.setattr(public_data, "fetch_pharmacies_near", fake_near)
    response = await client.get("/api/v1/pharmacies", params={"lat": 37.56, "lng": 126.97})
    assert [item["name"] for item in response.json()] == ["24시약국", "닫은약국"]
    assert response.json()[0]["distanceMeters"] == 50
    assert response.json()[0]["todayHours"] == "24시간"
    assert response.json()[1]["statusText"] == "영업시간 정보 없음"

    response = await client.get(
        "/api/v1/pharmacies", params={"lat": 37.56, "lng": 126.97, "openOnly": "true"}
    )
    assert [item["name"] for item in response.json()] == ["24시약국"]


async def test_pharmacies_require_coordinates(client):
    response = await client.get("/api/v1/pharmacies")
    assert response.status_code == 422


async def test_pharmacies_upstream_error(client, monkeypatch):
    async def broken(**_):
        raise public_data.PublicDataError("down")

    monkeypatch.setattr(public_data, "fetch_pharmacies_near", broken)
    response = await client.get("/api/v1/pharmacies", params={"lat": 37.56, "lng": 126.97})
    assert response.status_code == 502


@pytest.mark.parametrize(
    ("start", "end", "hour", "expected"),
    [
        ("0900", 2200, 12, (True, "영업 중 · 22:00까지")),
        (900, 2200, 8, (False, "영업 전 · 09:00 시작")),
        ("0900", 2200, 23, (False, "영업 종료")),
        ("2200", "0200", 1, (True, "영업 중 · 02:00까지")),
        ("0900", "0000", 20, (True, "영업 중 · 24:00까지")),
        ("0900", 2400, 20, (True, "영업 중 · 24:00까지")),
        (None, None, 12, (False, "영업시간 정보 없음")),
    ],
)
def test_pharmacy_open_status(start, end, hour, expected):
    assert open_status(start, end, datetime(2026, 10, 24, hour, 0, tzinfo=KST)) == expected


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("0900", "2200", "09:00~22:00"),
        ("0900", "0000", "09:00~24:00"),
        ("0900", 2400, "09:00~24:00"),
        ("2200", "0200", "22:00~02:00"),
        ("0000", 2400, "24시간"),
        (None, "2200", None),
    ],
)
def test_pharmacy_hours_text(start, end, expected):
    assert _hours_text(start, end) == expected


async def test_protected_route_requires_login(client):
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401


def test_parse_ocr_candidates_tolerates_wrapping_text():
    from app.modules.ocr.service import parse_candidates

    text = '결과입니다\n```json\n{"candidates": [{"name": "가나다정", "amount": 1, "timesPerDay": 3, "days": null}]}\n```'
    [candidate] = parse_candidates(text)
    assert (candidate.name, candidate.times_per_day, candidate.days) == ("가나다정", 3, None)
    assert parse_candidates("읽을 수 없어요") == []
