from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError
from sqlmodel import Session

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
TEST_ENV_FILE = BACKEND_DIR / ".env.test"
DEVELOPMENT_ENV_FILE = PROJECT_ROOT / ".env"
EXPECTED_TEST_IDENTITY = ("127.0.0.1", 5433, "app_test")


def normalize_host(host: str) -> str:
    lowered = host.lower()
    if lowered in {"localhost", "127.0.0.1", "::1"}:
        return "127.0.0.1"
    return lowered


def database_identity(raw_url: str) -> tuple[str, int, str]:
    url = make_url(raw_url)
    if not url.host or not url.database:
        raise ValueError("Database URL is incomplete")
    return normalize_host(url.host), url.port or 5432, url.database


def configure_test_database() -> None:
    test_values = dotenv_values(TEST_ENV_FILE) if TEST_ENV_FILE.exists() else {}
    test_url = os.getenv("TEST_DATABASE_URL") or test_values.get("TEST_DATABASE_URL")
    if not test_url:
        raise pytest.UsageError(
            "TEST_DATABASE_URL is required; configure backend/.env.test first"
        )

    parsed = make_url(test_url)
    if parsed.drivername != "postgresql+psycopg":
        raise pytest.UsageError(
            "TEST_DATABASE_URL must use postgresql+psycopg"
        )
    if not parsed.password:
        raise pytest.UsageError("TEST_DATABASE_URL must include a test password")

    test_identity = database_identity(test_url)
    if test_identity != EXPECTED_TEST_IDENTITY:
        raise pytest.UsageError(
            "TEST_DATABASE_URL must identify 127.0.0.1:5433/app_test"
        )

    development_url = os.getenv("DEV_DATABASE_URL")
    if not development_url and DEVELOPMENT_ENV_FILE.exists():
        development_url = dotenv_values(DEVELOPMENT_ENV_FILE).get("DATABASE_URL")
    if development_url and database_identity(development_url) == test_identity:
        raise pytest.UsageError(
            "TEST_DATABASE_URL must not equal the development database"
        )

    production_url = os.getenv("PRODUCTION_DATABASE_URL")
    if production_url and database_identity(production_url) == test_identity:
        raise pytest.UsageError(
            "TEST_DATABASE_URL must not equal the production database"
        )

    os.environ["DATABASE_URL"] = test_url
    os.environ["FASTAPI_ENV"] = "development"


try:
    configure_test_database()
except (ArgumentError, ValueError):
    raise pytest.UsageError(
        "Invalid TEST_DATABASE_URL configuration"
    ) from None


# All application imports must happen after the test database URL is installed.
from app.api.deps import get_db  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from tests.utils.user import authentication_token_from_email  # noqa: E402
from tests.utils.utils import get_superuser_token_headers  # noqa: E402

expected_identity = EXPECTED_TEST_IDENTITY
if database_identity(str(settings.DATABASE_URL)) != expected_identity:
    raise pytest.UsageError("Settings did not bind to the isolated test database")
if database_identity(str(engine.url)) != expected_identity:
    raise pytest.UsageError("Global Engine did not bind to the isolated test database")
if not isinstance(engine, Engine):
    raise pytest.UsageError("Database isolation expects a synchronous Engine")


@event.listens_for(engine, "connect")
def verify_actual_test_database(dbapi_connection, connection_record) -> None:
    del connection_record
    with dbapi_connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        database_name = cursor.fetchone()[0]
    if database_name != expected_identity[2]:
        raise RuntimeError(
            f"Refusing database connection: expected {expected_identity[2]}"
        )


@pytest.fixture
def db() -> Generator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
    )
    try:
        init_db(session)
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def override_get_db(db: Session) -> Generator[None]:
    def get_test_db() -> Generator[Session]:
        yield db

    app.dependency_overrides[get_db] = get_test_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture
def normal_user_token_headers(
    client: TestClient,
    db: Session,
) -> dict[str, str]:
    return authentication_token_from_email(
        client=client,
        email=settings.EMAIL_TEST_USER,
        db=db,
    )
