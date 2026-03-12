import pytest
from app import create_app, db as _db


@pytest.fixture(scope="session")
def app():
    application = create_app("testing")
    with application.app_context():
        _db.create_all()
        yield application
        _db.drop_all()


@pytest.fixture(scope="function")
def db(app):
    with app.app_context():
        yield _db
        _db.session.remove()
        _db.drop_all()
        _db.create_all()


@pytest.fixture(scope="function")
def client(app, db):
    return app.test_client()
