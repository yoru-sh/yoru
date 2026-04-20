import pytest


@pytest.mark.integration
async def test_backend_alive(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
