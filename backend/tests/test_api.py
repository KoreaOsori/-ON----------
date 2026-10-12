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
    assert [pair for pair in pairs if pair["contraindicated"]] == [
        {
            "first": "가나다정",
            "second": "마바사정",
            "contraindicated": True,
            "durContent": pairs[1]["durContent"],
            "easyExplanation": pairs[1]["easyExplanation"],
        }
    ]


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


async def test_pharmacies_open_only(client):
    response = await client.get(
        "/api/v1/pharmacies", params={"lat": 37.56, "lng": 126.97, "openOnly": "true"}
    )
    assert [item["name"] for item in response.json()] == ["온마음약국"]


async def test_protected_route_requires_login(client):
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401


def test_parse_ocr_candidates_tolerates_wrapping_text():
    from app.modules.ocr.service import parse_candidates

    text = '결과입니다\n```json\n{"candidates": [{"name": "가나다정", "amount": 1, "timesPerDay": 3, "days": null}]}\n```'
    [candidate] = parse_candidates(text)
    assert (candidate.name, candidate.times_per_day, candidate.days) == ("가나다정", 3, None)
    assert parse_candidates("읽을 수 없어요") == []
