from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.models import User, UserCreate
from tests.utils.utils import random_email, random_lower_string


def test_runtime_uses_isolated_test_database() -> None:
    expected_database = "app_test"
    assert make_url(str(settings.DATABASE_URL)).database == expected_database
    assert make_url(str(engine.url)).database == expected_database

    with engine.connect() as connection:
        actual_database = connection.exec_driver_sql(
            "SELECT current_database()"
        ).scalar_one()
    assert actual_database == expected_database


def test_crud_commit_does_not_escape_outer_transaction(db: Session) -> None:
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=random_lower_string(),
        ),
    )
    user_id = user.id
    assert db.exec(select(User).where(User.id == user_id)).first() is not None

    with engine.connect() as observer_connection:
        observed_user = observer_connection.execute(
            select(User).where(User.id == user_id)
        ).first()
    assert observed_user is None
