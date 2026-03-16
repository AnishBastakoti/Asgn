"""
conftest.py — Shared fixtures for all SkillPulse tests.

WHAT IS conftest.py?
    pytest automatically loads this file before any test runs.
    Fixtures defined here are available to ALL test files — no import needed.

WHAT IS A FIXTURE?
    A fixture is a function that prepares something a test needs.
    @pytest.fixture runs the setup, yields the resource, then runs cleanup.

    Example:
        @pytest.fixture
        def db():
            session = create_session()   # setup
            yield session                # test runs here
            session.close()             # cleanup (always runs, even if test fails)
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


# ── App client fixture ────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def client():
    """
    Creates a FastAPI TestClient for the whole test session.

    scope="session" means this fixture is created ONCE for all tests
    rather than before each test — faster for expensive setup.

    TestClient lets you call endpoints without running a real server:
        response = client.get("/health")
        assert response.status_code == 200
    """
    from main import app
    from app.database import get_db

    # Override get_db so tests use a mock DB, not your real PostgreSQL
    def override_get_db():
        db = MagicMock()
        yield db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    # Restore real DB after tests finish
    app.dependency_overrides.clear()


# ── Mock DB fixture ───────────────────────────────────────────────────────────
@pytest.fixture
def mock_db():
    """
    A fresh MagicMock database session for each test.

    MagicMock automatically creates any attribute or method you call on it.
    You then tell it what to return:

        mock_db.query().scalar.return_value = 42
        mock_db.query().all.return_value = [row1, row2]

    This means tests run instantly — no real DB needed.
    """
    return MagicMock()


# ── Sample data fixtures ──────────────────────────────────────────────────────
@pytest.fixture
def sample_occupation_id():
    """A real occupation ID from your DB (Software Engineer)."""
    return 273333


@pytest.fixture
def sample_city():
    """A real city from your demand data."""
    return "Sydney"


@pytest.fixture
def mock_skill_row():
    """
    Creates a fake DB row that looks like a real SQLAlchemy result.
    Tests that call .skill_name or .total_mentions will get real values.
    """
    row = MagicMock()
    row.skill_name = "Python"
    row.total_mentions = 150
    row.share_pct = 85.5
    return row


@pytest.fixture
def mock_occupation_row():
    """Fake occupation DB row."""
    row = MagicMock()
    row.id = 273333
    row.principal_title = "Software Engineer"
    row.skill_level = 1
    row.lead_statement = "Designs and develops software."
    row.main_tasks = "Write code; Test systems"
    row.licensing = ""
    row.caveats = ""
    row.specialisations = "AI Engineer; DevOps"
    row.skill_attributes = ""
    row.information_card = ""
    return row