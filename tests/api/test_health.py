def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_database_reachable(db):
    assert db.execute(__import__("sqlalchemy").text("select 1")).scalar() == 1
