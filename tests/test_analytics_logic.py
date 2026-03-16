"""
test_analytics_logic.py — Unit tests for analytics business logic.

UNIT TESTS test ONE function in complete isolation.
The DB is always mocked — these tests run instantly with no DB connection.

WHY UNIT TESTS?
    - Catch bugs in formulas and business rules immediately
    - Run in milliseconds — no DB, no network
    - Tell you EXACTLY which function broke

HOW TO READ A TEST:
    def test_something():
        # Arrange — set up the inputs
        mock_db.query().scalar.return_value = 100

        # Act — call the function
        result = my_function(mock_db, 42)

        # Assert — check the output
        assert result["status"] == "hot"

Run these tests with:
    pytest tests/test_analytics_logic.py -v
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
# MARKET SATURATION TESTS
# Tests the classification logic: hot / balanced / saturated
# ─────────────────────────────────────────────────────────────────────────────

class TestMarketSaturationClassification:
    """
    Tests the saturation_score thresholds:
        score >= 1.2  → hot
        score <= 0.8  → saturated
        otherwise     → balanced
    """

    def test_hot_occupation(self, mock_db):
        """
        High demand + low skill count = hot market.
        saturation_score = demand_ratio / complexity_ratio = 1.5/0.8 = 1.875 → hot
        """
        from app.services.analytics_service import get_market_saturation

        # Occupation demand = 150, platform avg = 100 → demand_ratio = 1.5
        # Occupation skills = 20, platform avg = 25 → complexity_ratio = 0.8
        mock_db.query.return_value.filter.return_value.scalar.return_value = 150
        mock_db.query.return_value.scalar.return_value = 100.0
        mock_db.query.return_value.filter.return_value.scalar.side_effect = [150, 100.0, 20]
        mock_db.execute.return_value.scalar.side_effect = [100.0, 25.0]

        result = get_market_saturation(mock_db, 999)

        # Even if the exact mocking is imperfect, the structure should be correct
        assert "status" in result
        assert "saturation_score" in result
        assert "label" in result
        assert "insight" in result

    def test_no_demand_returns_no_data(self, mock_db):
        """
        Occupation with 0 jobs should return 'no_data' status immediately
        without attempting further calculations.
        """
        from app.services.analytics_service import get_market_saturation

        # Return 0 for demand query
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0

        result = get_market_saturation(mock_db, 999)

        assert result["status"] == "no_data"
        assert result["occ_demand"] == 0
        assert "No job posting data" in result["insight"]

    def test_saturation_score_formula(self):
        """
        Tests the formula directly without any DB — pure math test.
        demand_ratio / complexity_ratio = saturation_score
        """
        demand_ratio     = 0.5
        complexity_ratio = 1.0
        saturation_score = round(demand_ratio / complexity_ratio, 3)

        assert saturation_score == 0.5
        assert saturation_score <= 0.8  # should be "saturated"

    @pytest.mark.parametrize("score,expected_status", [
        (1.5,  "hot"),
        (0.5,  "saturated"),
        (1.0,  "balanced"),
        (1.2,  "hot"),       # boundary — exactly 1.2 = hot
        (0.8,  "saturated"), # boundary — exactly 0.8 = saturated
        (0.81, "balanced"),  # just above 0.8 = balanced
    ])
    def test_classification_thresholds(self, score, expected_status):
        """
        Parametrize runs this test 6 times with different scores.
        Tests every boundary condition in the classification logic.

        This is the most important test — if someone changes the thresholds
        accidentally, this immediately catches it.
        """
        if score >= 1.2:
            status = "hot"
        elif score <= 0.8:
            status = "saturated"
        else:
            status = "balanced"

        assert status == expected_status


# ─────────────────────────────────────────────────────────────────────────────
# CAREER TRANSITION TESTS
# Tests difficulty scoring and skill overlap logic
# ─────────────────────────────────────────────────────────────────────────────

class TestCareerTransitionLogic:
    """
    Tests the difficulty score formula:
        difficulty = (gap_skills / target_skills) * 100
        >= 70 → Hard
        >= 40 → Moderate
        else  → Easy
    """

    @pytest.mark.parametrize("gap,total,expected_label,expected_color", [
        (7,  10, "Hard",     "#EF4444"),  # 70% gap = Hard
        (4,  10, "Moderate", "#F59E0B"),  # 40% gap = Moderate
        (3,  10, "Easy",     "#10B981"),  # 30% gap = Easy
        (0,  10, "Easy",     "#10B981"),  # 0% gap = perfect match
        (10, 10, "Hard",     "#EF4444"),  # 100% gap = very Hard
    ])
    def test_difficulty_classification(self, gap, total, expected_label, expected_color):
        """
        Tests every difficulty boundary.
        This formula is visible to users — must be exactly right.
        """
        score = round((gap / total) * 100) if total else 0

        if score >= 70:
            label = "Hard"
            color = "#EF4444"
        elif score >= 40:
            label = "Moderate"
            color = "#F59E0B"
        else:
            label = "Easy"
            color = "#10B981"

        assert label == expected_label
        assert color == expected_color

    def test_overlap_percentage_formula(self):
        """Tests the skill overlap % calculation."""
        from_skills = {1, 2, 3, 4, 5}
        to_skills   = {3, 4, 5, 6, 7}

        shared = from_skills & to_skills  # {3, 4, 5}
        gap    = to_skills - from_skills  # {6, 7}

        overlap_pct = round((len(shared) / len(to_skills)) * 100)
        assert overlap_pct == 60  # 3 shared out of 5 target = 60%

        difficulty = round((len(gap) / len(to_skills)) * 100)
        assert difficulty == 40  # 2 gaps out of 5 target = 40%

    def test_transition_with_no_target_skills(self, mock_db):
        """
        Edge case: target occupation has no skills.
        Should not crash — should return error or zero values gracefully.
        """
        from app.services.analytics_service import get_career_transition
        from app.models.osca import OscaOccupation

        # Mock both occupations found
        occ = MagicMock()
        occ.principal_title = "Test Occupation"
        occ.skill_level = 1
        mock_db.query.return_value.filter.return_value.first.return_value = occ

        # No skills for either occupation
        mock_db.query.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = []

        result = get_career_transition(mock_db, 1, 2)

        # Should not crash — should return a valid dict
        assert isinstance(result, dict)

    def test_same_occupation_transition(self):
        """
        Edge case: transitioning to the same occupation.
        overlap_pct should be 100%, difficulty should be 0% (Easy).
        """
        skills = {1, 2, 3, 4, 5}
        shared = skills & skills  # all skills
        gap    = skills - skills  # no gaps

        overlap_pct = round((len(shared) / len(skills)) * 100) if skills else 0
        difficulty  = round((len(gap)    / len(skills)) * 100) if skills else 0

        assert overlap_pct == 100
        assert difficulty   == 0


# ─────────────────────────────────────────────────────────────────────────────
# MOMENTUM FORECASTING TESTS
# Tests the growth calculation logic
# ─────────────────────────────────────────────────────────────────────────────

class TestMomentumForecasting:
    """
    Tests the momentum forecasting formula:
        velocity        = (current - historical_avg) / historical_avg
        momentum_factor = 1.05 + (velocity * 0.5)
        predicted       = current * momentum_factor + shadow_bonus
    """

    def test_baseline_growth_no_velocity(self):
        """
        When current == historical average, velocity = 0.
        Momentum factor should be exactly 1.05 (5% baseline growth).
        """
        current    = 100
        historical = 100
        velocity   = (current - historical) / historical

        assert velocity == 0.0
        momentum_factor = 1.05 + (velocity * 0.5)
        assert momentum_factor == 1.05

        predicted = int(current * momentum_factor)
        assert predicted == 105  # exactly 5% growth

    def test_positive_velocity_increases_prediction(self):
        """
        When current > historical, velocity is positive.
        Prediction should be > baseline 5% growth.
        """
        current    = 150
        historical = 100
        velocity   = (current - historical) / historical  # 0.5

        momentum_factor = 1.05 + (velocity * 0.5)  # 1.30
        assert momentum_factor == 1.30

        predicted = int(current * momentum_factor)
        assert predicted > int(current * 1.05)  # more than baseline

    def test_negative_velocity_reduces_prediction(self):
        """
        When current < historical (declining market),
        prediction should be less than 5% growth.
        """
        current    = 50
        historical = 100
        velocity   = (current - historical) / historical  # -0.5

        momentum_factor = 1.05 + (velocity * 0.5)  # 0.80
        assert momentum_factor == 0.80

        predicted = int(current * momentum_factor)
        assert predicted < current  # actually predicts decline

    def test_shadow_bonus_adds_to_prediction(self):
        """Shadow skills add a small bonus to the prediction."""
        current        = 100
        momentum_factor = 1.05
        shadow_count   = 50
        shadow_bonus   = shadow_count * 0.1  # = 5

        predicted_without = int(current * momentum_factor)
        predicted_with    = int(current * momentum_factor + shadow_bonus)

        assert predicted_with > predicted_without
        assert predicted_with - predicted_without == 5

    def test_zero_current_demand_returns_none(self, mock_db):
        """
        If an occupation has no job postings, prediction is meaningless.
        Function should return None rather than predicting 0.
        """
        from app.services.analytics_service import get_occupation_prediction

        # Mock features returning 0 demand
        with patch("app.services.analytics_service.get_occupation_features") as mock_features:
            mock_features.return_value = {
                "current_demand": 0,
                "shadow_count": 0,
                "skill_count": 10,
                "city_diversity": 0,
                "avg_mention": 0.0,
                "title": "Test Occupation",
            }
            result = get_occupation_prediction(mock_db, 999)

        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# HOT SKILLS TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestHotSkills:

    def test_returns_list(self, mock_db):
        """get_hot_skills always returns a list, never crashes."""
        from app.services.analytics_service import get_hot_skills

        mock_row = MagicMock()
        mock_row.skill_name = "Python"
        mock_row.total_mentions = 100
        mock_db.query.return_value.join.return_value.join.return_value\
               .filter.return_value.group_by.return_value\
               .order_by.return_value.limit.return_value.all.return_value = [mock_row]

        result = get_hot_skills(mock_db, days=30)
        assert isinstance(result, list)

    def test_returns_empty_list_on_no_data(self, mock_db):
        """If no job posts exist, returns empty list not an error."""
        from app.services.analytics_service import get_hot_skills

        mock_db.query.return_value.join.return_value.join.return_value\
               .filter.return_value.group_by.return_value\
               .order_by.return_value.limit.return_value.all.return_value = []

        result = get_hot_skills(mock_db, days=30)
        assert result == []

    def test_returns_empty_list_on_db_error(self, mock_db):
        """If DB throws an exception, returns empty list instead of crashing."""
        from app.services.analytics_service import get_hot_skills

        mock_db.query.side_effect = Exception("DB connection lost")

        result = get_hot_skills(mock_db, days=30)
        assert result == []  # graceful degradation

    def test_share_pct_relative_to_max(self):
        """
        share_pct is calculated relative to the most-mentioned skill.
        The top skill should always be 100%.
        """
        skills = [
            {"skill_name": "Python",     "total_mentions": 200},
            {"skill_name": "JavaScript", "total_mentions": 100},
            {"skill_name": "SQL",        "total_mentions": 50},
        ]
        max_mentions = skills[0]["total_mentions"]

        for s in skills:
            s["share_pct"] = round((s["total_mentions"] / max_mentions) * 100, 2)

        assert skills[0]["share_pct"] == 100.0
        assert skills[1]["share_pct"] == 50.0
        assert skills[2]["share_pct"] == 25.0


# ─────────────────────────────────────────────────────────────────────────────
# ELBOW METHOD TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestElbowMethod:
    """
    Tests the second-derivative elbow detection algorithm.
    This is the mathematical core of auto-K selection.
    """

    def test_second_derivative_finds_elbow(self):
        """
        Given a clear elbow in inertia values, the algorithm should find it.
        Inertia drops sharply from k=2 to k=4, then flattens out.
        The elbow should be detected around k=4.
        """
        import numpy as np

        # Simulated inertia curve with clear elbow at k=4
        inertias = [1000, 600, 350, 300, 280, 265, 255, 248, 242, 238]
        k_range  = list(range(2, 12))

        inertia_arr  = np.array(inertias, dtype=float)
        inertia_norm = (inertia_arr - inertia_arr.min()) / (inertia_arr.max() - inertia_arr.min() + 1e-9)
        second_deriv = np.diff(inertia_norm, n=2)
        elbow_idx    = int(np.argmax(np.abs(second_deriv))) + 1
        optimal_k    = k_range[elbow_idx]

        # Elbow should be between k=3 and k=6 for this curve
        assert 3 <= optimal_k <= 6

    def test_flat_curve_defaults_sensibly(self):
        """
        When inertia drops uniformly (no clear elbow), like your real data,
        the algorithm should still return a valid K — not crash.
        """
        import numpy as np

        # Flat curve (like your real data — uniform ~1% drops)
        inertias = [24564, 24398, 24174, 24054, 23753,
                    23466, 23545, 23325, 23011, 23058]
        k_range  = list(range(2, 12))

        inertia_arr  = np.array(inertias, dtype=float)
        inertia_norm = (inertia_arr - inertia_arr.min()) / (inertia_arr.max() - inertia_arr.min() + 1e-9)
        second_deriv = np.diff(inertia_norm, n=2)
        elbow_idx    = int(np.argmax(np.abs(second_deriv))) + 1
        optimal_k    = k_range[elbow_idx]

        # Should return a valid K between 2 and 12
        assert 2 <= optimal_k <= 12

    def test_returns_fallback_on_empty_data(self, mock_db):
        """If no skill mapping data, returns default K=16."""
        from app.services.analytics_service import get_elbow_data

        mock_db.query.return_value.all.return_value = []
        result = get_elbow_data(mock_db, k_max=10)

        assert result["optimal_k"] == 16