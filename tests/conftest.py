import pytest

from src.pipeline import db


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'pipeline.db'}"


@pytest.fixture
def con(db_url):
    c = db.connect(db_url)
    db.init_db(c)
    yield c
    c.close()
