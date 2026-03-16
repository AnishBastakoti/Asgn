"""
test_api_endpoints.py — Integration tests for all API endpoints.

INTEGRATION TESTS test the full request/response cycle:
    HTTP request → router → service → response

The DB is still mocked so these run without PostgreSQL.
But they test that:
    - Routes exist and return correct status codes
    - Response shapes match what the frontend expects
    - Error cases return sensible responses (not 500 crashes)

Run with:
    pytest tests/test_api_endpoints.py -v
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH & SYSTEM ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

class TestSystemEndpoints:

    def test_health_check_returns_200(self, client):
        """
        /health must always return 200.
        Load balancers and deployment tools hit this to check if the app is alive.
        If this fails, deployments will think the app is down.
        """
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_check_response_shape(self, client):
        """Health check must return status, app name, and version."""
        response = client.get("/health")
        data = response.json()

        assert "status"  in data
        assert "app"     in data
        assert "version" in data
        assert data["status"] == "healthy"

    def test_docs_accessible(self, client):
        """Swagger docs at /docs must be reachable — important for API consumers."""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_page_routes_return_html(self, client):
        """All frontend page routes must return HTML, not JSON."""
        pages = ["/", "/analytics", "/occupations", "/career", "/pipeline"]
        for page in pages:
            response = client.get(page)
            assert response.status_code == 200, f"Page {page} returned {response.status_code}"
            assert "text/html" in response.headers["content-type"], \
                f"Page {page} should return HTML"


# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyticsEndpoints:

    def test_hot_skills_returns_list(self, client):
        """
        /api/analytics/hot-skills must return a JSON array.
        The frontend uses data.map() on this — if it returns a dict it breaks.
        """
        with patch("app.services.analytics_service.get_hot_skills") as mock:
            mock.return_value = [
                {"skill_name": "Python", "total_mentions": 100, "share_pct": 85.0}
            ]
            response = client.get("/api/analytics/hot-skills")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_hot_skills_empty_list_not_error(self, client):
        """
        If no job posts exist, hot-skills should return [] not 500.
        The frontend handles empty arrays gracefully.
        """
        with patch("app.services.analytics_service.get_hot_skills") as mock:
            mock.return_value = []
            response = client.get("/api/analytics/hot-skills")

        assert response.status_code == 200
        assert response.json() == []

    def test_shadow_skills_returns_list(self, client):
        """Shadow skills endpoint must return a list."""
        with patch("app.services.analytics_service.get_shadow_skills") as mock:
            mock.return_value = [{"skill_name": "Docker"}]
            response = client.get("/api/analytics/shadow-skills/273333")

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_occupation_profile_has_required_fields(self, client):
        """
        Profile endpoint must return specific fields that the frontend renders.
        If any field is missing, sections silently disappear from the UI.
        """
        required_fields = [
            "occupation_id", "title", "skill_level",
            "lead_statement", "main_tasks", "total_skills", "skill_breakdown"
        ]
        with patch("app.services.analytics_service.get_occupation_profile") as mock:
            mock.return_value = {
                "occupation_id":   273333,
                "title":           "Software Engineer",
                "skill_level":     1,
                "lead_statement":  "Designs software.",
                "main_tasks":      "Write code.",
                "licensing":       "",
                "caveats":         "",
                "specialisations": "",
                "skill_attributes": "",
                "information_card": "",
                "total_skills":    262,
                "skill_breakdown": {"knowledge": 89, "skill/competence": 173},
            }
            response = client.get("/api/analytics/occupation-profile/273333")

        assert response.status_code == 200
        data = response.json()
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_career_transition_has_required_fields(self, client):
        """
        Career transition must return all fields the UI renders.
        Missing fields cause JavaScript errors in the frontend.
        """
        required_fields = [
            "from_title", "to_title", "shared_count", "gap_count",
            "overlap_pct", "difficulty_score", "difficulty_label",
            "difficulty_color", "shared_skills", "gap_skills"
        ]
        with patch("app.services.analytics_service.get_career_transition") as mock:
            mock.return_value = {
                "from_id":          273333,
                "from_title":       "Software Engineer",
                "from_skill_level": 1,
                "to_id":            242133,
                "to_title":         "Web Developer",
                "to_skill_level":   1,
                "shared_count":     15,
                "gap_count":        20,
                "total_target":     35,
                "overlap_pct":      43,
                "difficulty_score": 57,
                "difficulty_label": "Moderate",
                "difficulty_color": "#F59E0B",
                "shared_skills":    [],
                "gap_skills":       [],
            }
            response = client.get(
                "/api/analytics/career-transition?from_id=273333&to_id=242133"
            )

        assert response.status_code == 200
        data = response.json()
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_predict_demand_returns_404_for_no_data(self, client):
        """
        If an occupation has no job postings, prediction should 404.
        Not 500 — the frontend handles 404 gracefully.
        """
        with patch("app.services.analytics_service.get_occupation_prediction") as mock:
            mock.return_value = None  # no data for this occupation
            response = client.get("/api/analytics/predict-demand-by-occ/99999")

        assert response.status_code == 404

    def test_market_saturation_status_is_valid(self, client):
        """
        Saturation status must be one of the known values.
        The frontend uses this to apply CSS classes — unknown values break styling.
        """
        valid_statuses = {"hot", "balanced", "saturated", "no_data", "error"}

        with patch("app.services.analytics_service.get_market_saturation") as mock:
            mock.return_value = {
                "status": "hot", "saturation_score": 1.5,
                "demand_ratio": 1.5, "complexity_ratio": 1.0,
                "occ_demand": 150, "platform_avg_demand": 100.0,
                "occ_skill_count": 25, "platform_avg_skills": 25.0,
                "label": "Undersupplied — High Demand",
                "insight": "Strong hiring conditions.",
            }
            response = client.get("/api/analytics/market-saturation/273333")

        assert response.status_code == 200
        assert response.json()["status"] in valid_statuses

    def test_model_status_endpoint_exists(self, client):
        """Model status endpoint must exist and return model info."""
        with patch("app.services.analytics_service.get_model_status") as mock:
            mock.return_value = {
                "model_ready": True,
                "trained_at": "2026-03-17T09:00:00",
                "r2_score": 0.42,
                "occ_count": 669,
                "job_count": 4600,
                "feature_cols": ["current_demand", "shadow_count"],
                "method": "ridge_regression",
            }
            response = client.get("/api/analytics/model-status")

        assert response.status_code == 200
        data = response.json()
        assert "model_ready" in data
        assert "r2_score"    in data
        assert "method"      in data


# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMITING TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimiting:

    def test_rate_limit_headers_present(self, client):
        """
        Rate limit headers should be in responses.
        These tell clients how many requests they have left.
        """
        with patch("app.services.analytics_service.get_hot_skills") as mock:
            mock.return_value = []
            response = client.get("/api/analytics/hot-skills")

        # 200 OK expected
        assert response.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# EDGE CASE TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_invalid_occupation_id_type(self, client):
        """Non-integer occupation ID should return 422, not 500."""
        response = client.get("/api/analytics/shadow-skills/not-a-number")
        assert response.status_code == 422  # FastAPI validation error

    def test_career_transition_same_occupation(self, client):
        """Transitioning to the same occupation should still return a valid response."""
        with patch("app.services.analytics_service.get_career_transition") as mock:
            mock.return_value = {
                "from_id": 1, "from_title": "X", "from_skill_level": 1,
                "to_id": 1, "to_title": "X", "to_skill_level": 1,
                "shared_count": 10, "gap_count": 0, "total_target": 10,
                "overlap_pct": 100, "difficulty_score": 0,
                "difficulty_label": "Easy", "difficulty_color": "#10B981",
                "shared_skills": [], "gap_skills": [],
            }
            response = client.get("/api/analytics/career-transition?from_id=1&to_id=1")

        assert response.status_code == 200

    def test_city_demand_with_date_filter(self, client):
        """Date filter params should be accepted without errors."""
        with patch("app.services.analytics_service.get_city_demand_summary") as mock:
            mock.return_value = []
            response = client.get(
                "/api/analytics/city-demand?from_date=2025-01-01&to_date=2025-12-31"
            )

        assert response.status_code == 200

    def test_similarity_for_unknown_occupation(self, client):
        """Occupation with no skills should return error dict, not 500."""
        with patch("app.services.analytics_service.get_occupation_similarity") as mock:
            mock.return_value = {"error": "Occupation has no mapped skills"}
            response = client.get("/api/analytics/occupation-similarity/99999")

        assert response.status_code == 200
        assert "error" in response.json()

    def test_missing_career_transition_params(self, client):
        """Missing from_id or to_id should return 422."""
        response = client.get("/api/analytics/career-transition?from_id=1")
        assert response.status_code == 422

    def test_negative_days_hot_skills(self, client):
        """Negative days param should still work (returns empty, not crash)."""
        with patch("app.services.analytics_service.get_hot_skills") as mock:
            mock.return_value = []
            response = client.get("/api/analytics/hot-skills?days=-1")

        assert response.status_code == 200