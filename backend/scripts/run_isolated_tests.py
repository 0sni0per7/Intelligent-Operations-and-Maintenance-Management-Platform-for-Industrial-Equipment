from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
TEST_ENV_FILE = BACKEND_DIR / ".env.test"
DEVELOPMENT_ENV_FILE = PROJECT_ROOT / ".env"
EXPECTED_TEST_IDENTITY = ("127.0.0.1", 5433, "app_test")

logging.basicConfig(level=logging.INFO, format="%(message)s")
LOGGER = logging.getLogger(__name__)


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


def load_test_database_url() -> str:
    test_values = dotenv_values(TEST_ENV_FILE) if TEST_ENV_FILE.exists() else {}
    test_url = os.getenv("TEST_DATABASE_URL") or test_values.get("TEST_DATABASE_URL")
    if not test_url:
        raise ValueError(
            "TEST_DATABASE_URL is required; configure backend/.env.test first"
        )

    parsed = make_url(test_url)
    if parsed.drivername != "postgresql+psycopg":
        raise ValueError("TEST_DATABASE_URL must use postgresql+psycopg")
    if not parsed.password:
        raise ValueError("TEST_DATABASE_URL must include a test password")

    test_identity = database_identity(test_url)
    if test_identity != EXPECTED_TEST_IDENTITY:
        raise ValueError(
            "TEST_DATABASE_URL must identify 127.0.0.1:5433/app_test"
        )

    development_url = os.getenv("DEV_DATABASE_URL")
    if not development_url and DEVELOPMENT_ENV_FILE.exists():
        development_url = dotenv_values(DEVELOPMENT_ENV_FILE).get("DATABASE_URL")
    if development_url and database_identity(development_url) == test_identity:
        raise ValueError("TEST_DATABASE_URL must not equal the development database")

    production_url = os.getenv("PRODUCTION_DATABASE_URL")
    if production_url and database_identity(production_url) == test_identity:
        raise ValueError("TEST_DATABASE_URL must not equal the production database")

    return test_url


def run() -> int:
    try:
        test_url = load_test_database_url()
        test_identity = database_identity(test_url)
    except (ArgumentError, ValueError):
        LOGGER.error("Invalid TEST_DATABASE_URL configuration")
        return 2

    env = os.environ.copy()
    env["DATABASE_URL"] = test_url
    env["FASTAPI_ENV"] = "development"
    coverage_title = " ".join(sys.argv[1:]).strip() or "coverage"
    host, port, database = test_identity
    LOGGER.info(
        "[db-isolation] host=%s port=%s database=%s",
        host,
        port,
        database,
    )

    commands = [
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        [sys.executable, "-m", "coverage", "run", "-m", "pytest", "tests/"],
        [sys.executable, "-m", "coverage", "report"],
        [
            sys.executable,
            "-m",
            "coverage",
            "html",
            "--title",
            coverage_title,
        ],
    ]

    try:
        for command in commands:
            subprocess.run(
                command,
                cwd=BACKEND_DIR,
                env=env,
                check=True,
            )
    except subprocess.CalledProcessError as exc:
        return exc.returncode or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
