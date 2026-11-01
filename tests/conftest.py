"""Test harness.

API tests run against the real Postgres test database. Each test runs inside an outer transaction
on one connection; the app's session joins it via savepoints, and everything is rolled back at the end.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from mission_control.api.app import create_app
from mission_control.clock import FixedClock
from mission_control.config import get_settings
from mission_control.db.session import get_db

NOW = datetime(2027, 1, 15, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = get_settings().test_database_url
    _ensure_database(url)
    eng = create_engine(url)
    _prepare_schema(eng)
    yield eng
    eng.dispose()


def _ensure_database(url: str) -> None:
    """Create the test database on first run (no bind-mounted init scripts needed)."""
    target = create_engine(url).url
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(text("select 1 from pg_database where datname = :n"), {"n": target.database})
        if exists.scalar() is None:
            conn.execute(text(f'create database "{target.database}"'))
    admin.dispose()


def _prepare_schema(eng: Engine) -> None:
    """Bring the test database to the latest migration (no-op until migrations exist)."""
    try:
        from mission_control.db.migrate import upgrade_to_head
    except ImportError:
        return
    upgrade_to_head(str(eng.url.render_as_string(hide_password=False)))


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    conn = engine.connect()
    trans = conn.begin()
    try:
        yield conn
    finally:
        trans.rollback()
        conn.close()


@pytest.fixture
def db(connection: Connection) -> Iterator[Session]:
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def app(db: Session, clock: FixedClock):
    application = create_app(clock=clock)

    def _get_db() -> Iterator[Session]:
        yield db

    application.dependency_overrides[get_db] = _get_db
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def login(client: TestClient, member, org) -> dict[str, str]:
    """Log a factory-made member in and return auth headers."""
    from tests.factories import PASSWORD

    resp = client.post("/v1/auth/login", json={"email": member.user.email, "password": PASSWORD, "org": org.slug})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture
def auth_headers(client):
    """Callable fixture: auth_headers(member, org) -> headers."""
    return lambda member, org: login(client, member, org)
