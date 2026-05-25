import pytest
from sqlmodel import Session, SQLModel, create_engine

from LiveNotifyUID.database import LiveSubscription


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
