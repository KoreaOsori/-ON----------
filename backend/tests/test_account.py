"""이메일 로그인 → 동의 → 건강정보 → 복용약·복약 기록 (서버 저장)"""

HEALTH = {
    "birth": "1990-05-01",
    "gender": "여성",
    "height": 160,
    "weight": 50,
    "pregnant": "임신 아님",
    "medicineStatus": "약을 선택할게요",
    "medicines": ["타이레놀정500밀리그람"],
    "medicineItems": [{"id": "200000001", "name": "타이레놀정500밀리그람", "saleStatus": "판매"}],
    "conditions": "없음",
}


async def login(client, email="Hong@Example.com"):
    response = await client.post("/api/v1/auth/login", json={"email": email})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_email_login_creates_then_reuses_account(db_client):
    first = await login(db_client)
    me = (await db_client.get("/api/v1/users/me", headers=first)).json()
    assert me["email"] == "hong@example.com" and me["nickname"] == "hong" and me["provider"] == "email"
    again = await login(db_client, " hong@example.com ")
    assert (await db_client.get("/api/v1/users/me", headers=again)).json()["id"] == me["id"]


async def test_login_rejects_non_email(db_client):
    assert (await db_client.post("/api/v1/auth/login", json={"email": "hong"})).status_code == 422


async def test_social_and_demo_login_removed(db_client):
    assert (await db_client.get("/api/v1/auth/oauth/kakao/authorize")).status_code == 404
    assert (await db_client.post("/api/v1/auth/demo-login")).status_code == 404


async def test_health_profile_requires_consent_and_round_trips(db_client):
    headers = await login(db_client)
    assert (await db_client.get("/api/v1/users/me/health-profile", headers=headers)).json() is None
    assert (
        await db_client.put("/api/v1/users/me/health-profile", json=HEALTH, headers=headers)
    ).status_code == 403
    consents = {"consents": {"terms": True, "privacy": True, "health": True}}
    assert (
        await db_client.put("/api/v1/users/me/consents", json=consents, headers=headers)
    ).status_code == 204
    assert (
        await db_client.put("/api/v1/users/me/health-profile", json=HEALTH, headers=headers)
    ).status_code == 200
    saved = (await db_client.get("/api/v1/users/me/health-profile", headers=headers)).json()
    assert saved["medicineItems"][0]["id"] == "200000001" and saved["medicines"] == HEALTH["medicines"]


async def test_medication_crud_and_logs(db_client):
    headers = await login(db_client)
    other = await login(db_client, "other@example.com")
    # 복용 정보 없이도 등록 (건강정보에서 이름만 고른 약)
    created = await db_client.post("/api/v1/medications", json={"name": "타이레놀정"}, headers=headers)
    assert created.status_code == 201 and created.json()["timesPerDay"] is None
    assert created.json()["itemSeq"] is None
    medication_id = created.json()["id"]
    # 약 검색에서 고른 약은 품목기준코드를 함께 저장한다
    picked = {"name": "타이레놀정500밀리그람", "itemSeq": "200000001"}
    created = await db_client.post("/api/v1/medications", json=picked, headers=headers)
    assert created.status_code == 201 and created.json()["itemSeq"] == "200000001"
    listed = (await db_client.get("/api/v1/medications", headers=headers)).json()
    assert [item["itemSeq"] for item in listed] == [None, "200000001"]
    bad = {"name": "타이레놀정", "itemSeq": "abc"}
    assert (await db_client.post("/api/v1/medications", json=bad, headers=headers)).status_code == 422
    patch = {"amount": 1, "timesPerDay": 2, "days": 5, "startDate": "2026-10-24"}
    updated = await db_client.patch(f"/api/v1/medications/{medication_id}", json=patch, headers=headers)
    assert updated.json()["timesPerDay"] == 2
    # 다른 사람 약은 고칠 수 없다
    assert (
        await db_client.patch(f"/api/v1/medications/{medication_id}", json=patch, headers=other)
    ).status_code == 404

    log = {"date": "2026-10-24", "slot": "아침 식후", "taken": True}
    assert (
        await db_client.put(f"/api/v1/medications/{medication_id}/logs", json=log, headers=headers)
    ).status_code == 204
    logs = (
        await db_client.get("/api/v1/medications/logs", params={"month": "2026-10"}, headers=headers)
    ).json()
    assert logs == [{"date": "2026-10-24", "slot": "아침 식후", "taken": True, "medicationId": medication_id}]
    assert (
        await db_client.get("/api/v1/medications/logs", params={"month": "2026-10"}, headers=other)
    ).json() == []

    assert (await db_client.delete("/api/v1/medications", headers=headers)).status_code == 204
    assert (await db_client.get("/api/v1/medications", headers=headers)).json() == []


async def test_login_blocked_with_default_jwt_secret_outside_local(db_client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "jwt_secret_key", "change-me")
    assert (await db_client.post("/api/v1/auth/login", json={"email": "a@b.co"})).status_code == 503
