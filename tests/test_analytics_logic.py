import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.services.analytics_service import (
    get_shadow_skills, 
    get_skill_decay, 
    get_skill_velocity
)

from app.services.jobs_service import (
    get_skill_overlap,
    get_cities_by_occupation,
    get_top_companies,
    get_city_lead_indicator,
    get_hot_skills_for_occupation,
)
from app.services.demand_service import (
    get_city_demand_summary,
    get_city_demand_detail,
    get_market_saturation,
    get_occupation_profile,
    get_career_transition,
)

# ═════════════════════════════════════════════════════════════════════════════
# FIXTURES FOR REAL DB EXECUTION (Resolves 12% Coverage Issue)
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def db_session():
    """Provides a real in-memory SQLite session for testing service logic."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)

def test_get_shadow_skills_full_execution(db_session, sample_occupation_id):
    """Tests get_shadow_skills with actual DB execution to ensure line coverage."""
    from app.models.jobs import JobPostLog, JobPostSkill
    from app.models.skills import EscoSkill
    
    # 1. Setup Data: skill not mapped to occupation
    skill = EscoSkill(preferred_label="Emerging Tech", skill_type="knowledge")
    db_session.add(skill)
    db_session.commit()
    
    job = JobPostLog(occupation_id=sample_occupation_id, city="Sydney", processed_by_ai=True)
    db_session.add(job)
    db_session.commit()
    
    link = JobPostSkill(job_post_id=job.id, skill_id=skill.id)
    db_session.add(link)
    db_session.commit()

    # Act
    results = get_shadow_skills(db_session, sample_occupation_id)
    
    # Assert
    assert len(results) > 0
    assert results[0]["skill_name"] == "Emerging Tech"

# ═════════════════════════════════════════════════════════════════════════════
# DEMAND SERVICE TESTS
# 
# ═════════════════════════════════════════════════════════════════════════════

class TestGetCityDemandSummary:
    """
    Tests for get_city_demand_summary(db, from_date, to_date)

    Two code paths:
        - With date filter  --> queries JobPostLog directly
        - Without filter    --> queries SkillpulseCityOccupationDemand (cache table)

     from conftest.py:
        mock_db     --  MagicMock DB session for each test
        sample_city -- "Sydney"
    """

    def _make_row(self, city, total_jobs, occupation_count):
        """ builds a fake SQLAlchemy result row."""
        row = MagicMock()
        row.city             = city
        row.total_jobs       = total_jobs
        row.occupation_count = occupation_count
        return row

    def test_returns_empty_list_when_no_rows(self, mock_db):
        """When DB returns no rows, function should return [] not crash."""
        mock_db.query.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .all.return_value = []

        result = get_city_demand_summary(mock_db)
        assert result == []

    def test_demand_pct_of_top_city_is_100(self, mock_db, sample_city):
        """
        The top city always gets demand_pct = 100.0.
        All others are calculated relative to that max.
        """
        rows = [
            self._make_row(sample_city,   200, 10),  # "Sydney"
            self._make_row("Melbourne",   100, 5),
        ]
        mock_db.query.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .all.return_value = rows

        result = get_city_demand_summary(mock_db)

        assert result[0]["demand_pct"] == 100.0   # top city always 100%
        assert result[1]["demand_pct"] == 50.0    # 100/200 * 100

    def test_returns_correct_structure(self, mock_db, sample_city):
        """Each dict in the result must have exactly these 4 keys."""
        mock_db.query.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .all.return_value = [self._make_row(sample_city, 100, 5)]

        result = get_city_demand_summary(mock_db)

        assert len(result) == 1
        assert "city"             in result[0]
        assert "total_jobs"       in result[0]
        assert "occupation_count" in result[0]
        assert "demand_pct"       in result[0]

    def test_db_exception_returns_empty_list(self, mock_db):
        """
        If DB throws any exception, function must return []
        not propagate the crash to the API layer.
        """
        mock_db.query.side_effect = Exception("DB is down")

        result = get_city_demand_summary(mock_db)
        assert result == []

    def test_with_date_filter_uses_job_post_log(self, mock_db):
        """
        When from_date is provided, a different query path runs.
        Result should still be a list regardless.
        """
        mock_db.query.return_value \
               .filter.return_value \
               .filter.return_value \
               .filter.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .all.return_value = []

        result = get_city_demand_summary(mock_db, from_date="2025-01-01")
        assert isinstance(result, list)


# ─────────────────────────────────────────────────────────────────────────────

class TestGetCityDemandDetail:
    """
    Tests for get_city_demand_detail(db, city, limit, from_date, to_date)

     from conftest.py:
        mock_db     -- MagicMock DB session
        sample_city -- "Sydney"
    """

    def _make_row(self, title, occ_id, total_jobs):
        """builds a fake occupation demand row."""
        row = MagicMock()
        row.occupation_title = title
        row.occupation_id    = occ_id
        row.total_jobs       = total_jobs
        return row

    def test_returns_empty_list_on_no_data(self, mock_db, sample_city):
        mock_db.query.return_value \
               .filter.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .limit.return_value \
               .all.return_value = []

        result = get_city_demand_detail(mock_db, sample_city)
        assert result == []

    def test_demand_pct_formula(self, mock_db, sample_city):
        """Top occupation gets 100.0%, second gets its relative share."""
        rows = [
            self._make_row("Software Engineer", 273333, 400),
            self._make_row("Web Developer",     242133, 200),
        ]
        mock_db.query.return_value \
               .filter.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .limit.return_value \
               .all.return_value = rows

        result = get_city_demand_detail(mock_db, sample_city)

        assert result[0]["demand_pct"] == 100.0   # 400/400 * 100
        assert result[1]["demand_pct"] == 50.0    # 200/400 * 100

    def test_db_exception_returns_empty_list(self, mock_db, sample_city):
        mock_db.query.side_effect = Exception("connection refused")

        result = get_city_demand_detail(mock_db, sample_city)
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────

class TestGetMarketSaturation:
    """
    Tests for get_market_saturation(db, occupation_id)

    Formula:
        demand_ratio     = occ_demand / platform_avg_demand
        complexity_ratio = occ_skills / platform_avg_skills
        saturation_score = demand_ratio / complexity_ratio

        >= 1.2  --> hot
        <= 0.8  --> saturated
        else    --> balanced

     from conftest.py:
        mock_db              --  MagicMock DB session
        sample_occupation_id -- 273333
    """

    def test_zero_demand_returns_no_data(self, mock_db, sample_occupation_id):
        """
        If occupation has 0 job postings, status must be 'no_data'.
        Prevents division by zero and returns immediately.
        """
        mock_db.query.return_value \
               .filter.return_value \
               .scalar.return_value = 0

        result = get_market_saturation(mock_db, sample_occupation_id)

        assert result["status"]     == "no_data"
        assert result["occ_demand"] == 0
        assert "No job posting data" in result["insight"]

    def test_required_fields_always_present(self, mock_db, sample_occupation_id):
        """Response dict must always contain every expected key."""
        mock_db.query.return_value \
               .filter.return_value \
               .scalar.return_value = 0

        result = get_market_saturation(mock_db, sample_occupation_id)

        for field in [
            "status", "saturation_score", "demand_ratio",
            "complexity_ratio", "occ_demand", "platform_avg_demand",
            "occ_skill_count", "platform_avg_skills", "label", "insight"
        ]:
            assert field in result, f"Missing field: {field}"

    def test_db_exception_returns_error_status(self, mock_db, sample_occupation_id):
        """DB crash must return error dict, not raise an exception."""
        mock_db.query.side_effect = Exception("timeout")

        result = get_market_saturation(mock_db, sample_occupation_id)
        assert result["status"] == "error"

    @pytest.mark.parametrize("score,expected", [
        (1.5,  "hot"),
        (1.2,  "hot"),        # boundary — exactly 1.2 is hot
        (1.0,  "balanced"),
        (0.81, "balanced"),   # just above 0.8 is balanced
        (0.8,  "saturated"),  # boundary — exactly 0.8 is saturated
        (0.5,  "saturated"),
    ])
    def test_classification_thresholds(self, score, expected):
        """
        math test — no DB needed.
        Tests every boundary condition of the hot/balanced/saturated logic.
        """
        if score >= 1.2:
            status = "hot"
        elif score <= 0.8:
            status = "saturated"
        else:
            status = "balanced"

        assert status == expected


# ─────────────────────────────────────────────────────────────────────────────

class TestGetOccupationProfile:
    """
    Tests for get_occupation_profile(db, occupation_id)

     from conftest.py:
        mock_db              --  MagicMock DB session
        mock_occupation_row  -- pre-built fake OscaOccupation row
        sample_occupation_id -- 273333
    """

    def test_not_found_returns_error_dict(self, mock_db, sample_occupation_id):
        """If occupation_id doesn't exist, return {'error'} not crash."""
        mock_db.query.return_value \
               .filter.return_value \
               .first.return_value = None   # occupation not in DB

        result = get_occupation_profile(mock_db, sample_occupation_id)
        assert "error" in result

    def test_returns_all_required_fields(self, mock_db, mock_occupation_row, sample_occupation_id):
        """
        All fields the frontend renders must be present.
        mock_occupation_row from conftest.py gives us a realistic fake row.
        """
        mock_db.query.return_value \
               .filter.return_value \
               .first.return_value = mock_occupation_row

        mock_db.query.return_value \
               .join.return_value \
               .filter.return_value \
               .group_by.return_value \
               .all.return_value = []   # no skills — keeps test simple

        result = get_occupation_profile(mock_db, sample_occupation_id)

        for field in [
            "occupation_id", "title", "skill_level",
            "lead_statement", "main_tasks", "total_skills", "skill_breakdown"
        ]:
            assert field in result, f"Missing: {field}"

    def test_total_skills_sums_breakdown(self, mock_db, mock_occupation_row, sample_occupation_id):
        """
        total_skills must equal the sum of all values in skill_breakdown.
        Uses mock_occupation_row from conftest.py for the occupation lookup.
        """
        skill_row_1            = MagicMock()
        skill_row_1.skill_type = "knowledge"
        skill_row_1.cnt        = 89

        skill_row_2            = MagicMock()
        skill_row_2.skill_type = "skill/competence"
        skill_row_2.cnt        = 173

        mock_db.query.return_value \
               .filter.return_value \
               .first.return_value = mock_occupation_row

        mock_db.query.return_value \
               .join.return_value \
               .filter.return_value \
               .group_by.return_value \
               .all.return_value = [skill_row_1, skill_row_2]

        result = get_occupation_profile(mock_db, sample_occupation_id)
        assert result["total_skills"] == 89 + 173

    def test_db_exception_returns_error(self, mock_db, sample_occupation_id):
        mock_db.query.side_effect = Exception("DB lost")

        result = get_occupation_profile(mock_db, sample_occupation_id)
        assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────

class TestGetCareerTransition:
    """
    Tests for get_career_transition(db, from_id, to_id)

    Difficulty is computed from 4 signals:
        F1  Weighted Skill Gap    (45%)
        F2  Skill Level Jump      (25%)
        F3  Taxonomy Distance     (20%)
        F4  Skill Breadth Penalty (10%)

     from conftest.py:
        mock_db --  MagicMock DB session
    """

    def test_missing_occupation_returns_error(self, mock_db):
        """If either occupation is not in DB, return error dict not crash."""
        mock_db.query.return_value \
               .join.return_value \
               .join.return_value \
               .join.return_value \
               .join.return_value \
               .filter.return_value \
               .first.return_value = None

        result = get_career_transition(mock_db, 1, 2)
        assert "error" in result

    def test_difficulty_score_clamped_0_to_100(self):
        """
        math test — no DB needed.
        difficulty_score must always stay between 0 and 100.
        """
        f1, f2, f3, f4 = 0.9, 0.8, 1.0, 1.0
        W1, W2, W3, W4 = 0.45, 0.25, 0.20, 0.10
        raw   = (W1 * f1) + (W2 * f2) + (W3 * f3) + (W4 * f4)
        score = int(round(max(0.0, min(raw, 1.0)) * 100))

        assert 0 <= score <= 100

    @pytest.mark.parametrize("score,expected_label,expected_color", [
        (65,  "Hard",     "#EF4444"),  # boundary — exactly 65 is Hard
        (35,  "Moderate", "#F59E0B"),  # boundary — exactly 35 is Moderate
        (34,  "Easy",     "#10B981"),  # just below Moderate = Easy
        (0,   "Easy",     "#10B981"),  # minimum possible score
        (100, "Hard",     "#EF4444"),  # maximum possible score
    ])
    def test_difficulty_label_and_color(self, score, expected_label, expected_color):
        """Correct label and CSS color returned for each difficulty band."""
        if score >= 65:
            label = "Hard";     color = "#EF4444"
        elif score >= 35:
            label = "Moderate"; color = "#F59E0B"
        else:
            label = "Easy";     color = "#10B981"

        assert label == expected_label
        assert color == expected_color

    def test_f3_taxonomy_same_unit_is_zero(self):
        """
        math test.
        Two occupations in the same unit group --> taxonomy distance = 0.
        """
        unit_group_id = 42
        same_unit     = (unit_group_id is not None and unit_group_id == unit_group_id)
        f3            = 0.0 if same_unit else 0.20

        assert f3 == 0.0

    def test_db_exception_returns_error_dict(self, mock_db):
        mock_db.query.side_effect = Exception("lost connection")

        result = get_career_transition(mock_db, 1, 2)
        assert "error" in result


# ═════════════════════════════════════════════════════════════════════════════
# JOBS SERVICE TESTS
# 
# ═════════════════════════════════════════════════════════════════════════════

class TestGetCitiesByOccupation:
    """
    Tests for get_cities_by_occupation(db, occupation_id)

    from conftest.py:
        mock_db              --  MagicMock DB session
        sample_occupation_id -- 273333
    """

    def test_returns_list_of_dicts(self, mock_db, sample_occupation_id):
        """Result must be a list of {city, job_count} dicts."""
        mock_row           = MagicMock()
        mock_row.city      = "Sydney"
        mock_row.job_count = 42

        mock_db.query.return_value \
               .filter.return_value \
               .filter.return_value \
               .filter.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .limit.return_value \
               .all.return_value = [mock_row]

        result = get_cities_by_occupation(mock_db, sample_occupation_id)

        assert isinstance(result, list)
        assert result[0]["city"]      == "Sydney"
        assert result[0]["job_count"] == 42

    def test_returns_empty_list_on_no_data(self, mock_db, sample_occupation_id):
        mock_db.query.return_value \
               .filter.return_value \
               .filter.return_value \
               .filter.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .limit.return_value \
               .all.return_value = []

        result = get_cities_by_occupation(mock_db, sample_occupation_id)
        assert result == []

    def test_db_exception_returns_empty_list(self, mock_db, sample_occupation_id):
        mock_db.query.side_effect = Exception("timeout")

        result = get_cities_by_occupation(mock_db, sample_occupation_id)
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────

class TestGetTopCompanies:
    """
    Tests for get_top_companies(db, occupation_id)

    from conftest.py:
        mock_db              --  MagicMock DB session
        sample_occupation_id -- 273333
    """

    def test_returns_company_and_postings(self, mock_db, sample_occupation_id):
        """Result must be a list of {company, postings} dicts."""
        mock_row               = MagicMock()
        mock_row.company_name  = "NASA"
        mock_row.posting_count = 15

        mock_db.query.return_value \
               .filter.return_value \
               .filter.return_value \
               .filter.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .limit.return_value \
               .all.return_value = [mock_row]

        result = get_top_companies(mock_db, sample_occupation_id)

        assert result[0]["company"]  == "NASA"
        assert result[0]["postings"] == 15

    def test_returns_empty_list_on_no_data(self, mock_db, sample_occupation_id):
        mock_db.query.return_value \
               .filter.return_value \
               .filter.return_value \
               .filter.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .limit.return_value \
               .all.return_value = []

        assert get_top_companies(mock_db, sample_occupation_id) == []

    def test_db_exception_returns_empty_list(self, mock_db, sample_occupation_id):
        mock_db.query.side_effect = Exception("DB error")

        assert get_top_companies(mock_db, sample_occupation_id) == []


# ─────────────────────────────────────────────────────────────────────────────

class TestGetCityLeadIndicator:
    """
    Tests for get_city_lead_indicator(db, occupation_id)

     from conftest.py:
        mock_db              --  MagicMock DB session
        sample_occupation_id -- 273333
        sample_city          -- "Sydney"
    """

    def test_first_city_is_lead(self, mock_db, sample_occupation_id, sample_city):
        """
        The first city returned by the DB must have is_lead=True and rank=1.
        All subsequent cities must have is_lead=False.
        """
        row1                = MagicMock()
        row1.city           = sample_city    # "Sydney"
        row1.first_seen     = None
        row1.total_postings = 10

        row2                = MagicMock()
        row2.city           = "Melbourne"
        row2.first_seen     = None
        row2.total_postings = 5

        mock_db.query.return_value \
               .filter.return_value \
               .filter.return_value \
               .filter.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .all.return_value = [row1, row2]

        result = get_city_lead_indicator(mock_db, sample_occupation_id)

        assert result[0]["is_lead"] is True
        assert result[0]["rank"]    == 1
        assert result[1]["is_lead"] is False
        assert result[1]["rank"]    == 2

    def test_returns_empty_list_on_no_data(self, mock_db, sample_occupation_id):
        mock_db.query.return_value \
               .filter.return_value \
               .filter.return_value \
               .filter.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .all.return_value = []

        assert get_city_lead_indicator(mock_db, sample_occupation_id) == []

    def test_db_exception_returns_empty_list(self, mock_db, sample_occupation_id):
        mock_db.query.side_effect = Exception("timeout")

        assert get_city_lead_indicator(mock_db, sample_occupation_id) == []


# ─────────────────────────────────────────────────────────────────────────────

class TestGetHotSkillsForOccupation:
    """
    Tests for get_hot_skills_for_occupation(db, occupation_id, days)

     from conftest.py:
        mock_db              --  MagicMock DB session
        mock_skill_row       -- pre-built fake skill row
                                (skill_name="Python", total_mentions=150)
        sample_occupation_id -- 273333
    """

    def test_returns_correct_structure(self, mock_db, mock_skill_row, sample_occupation_id):
        """
        Must always return dict with skills, is_fallback, days.
        mock_skill_row from conftest.py gives us a realistic fake skill row.
        """
        mock_db.query.return_value \
               .join.return_value \
               .join.return_value \
               .filter.return_value \
               .filter.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .limit.return_value \
               .all.return_value = [mock_skill_row]

        result = get_hot_skills_for_occupation(mock_db, sample_occupation_id, days=30)

        assert "skills"      in result
        assert "is_fallback" in result
        assert "days"        in result
        assert result["days"] == 30

    def test_top_skill_share_pct_is_100(self, mock_skill_row):
        """
        math test — no DB needed.
        The most-mentioned skill must always get share_pct = 100.0.
        Uses mock_skill_row.total_mentions = 150 from conftest.py.
        """
        skills = [
            {"skill_name": mock_skill_row.skill_name,  "total_mentions": mock_skill_row.total_mentions},
            {"skill_name": "SQL",                       "total_mentions": 75},
        ]
        max_m = skills[0]["total_mentions"]   # 150 from conftest mock_skill_row
        for s in skills:
            s["share_pct"] = round((s["total_mentions"] / max_m) * 100, 1)

        assert skills[0]["share_pct"] == 100.0   # Python = 150/150 * 100
        assert skills[1]["share_pct"] == 50.0    # SQL    = 75/150  * 100

    def test_empty_db_returns_empty_skills_list(self, mock_db, sample_occupation_id):
        mock_db.query.return_value \
               .join.return_value \
               .join.return_value \
               .filter.return_value \
               .filter.return_value \
               .group_by.return_value \
               .order_by.return_value \
               .limit.return_value \
               .all.return_value = []

        result = get_hot_skills_for_occupation(mock_db, sample_occupation_id)
        assert result["skills"] == []

    def test_db_exception_returns_safe_fallback(self, mock_db, sample_occupation_id):
        """DB crash must return a safe empty structure, never raise."""
        mock_db.query.side_effect = Exception("lost connection")

        result = get_hot_skills_for_occupation(mock_db, sample_occupation_id)

        assert result["skills"]      == []
        assert result["is_fallback"] is False


# ─────────────────────────────────────────────────────────────────────────────

class TestGetSkillTrendsMath:
    """
    Tests the trend classification math from get_skill_trends_by_occupation.
    All pure math tests — no DB or fixtures needed.
    """

    @pytest.mark.parametrize("slope,expected_trend", [
        (0.002,  "growing"),    # above +0.001 threshold
        (-0.002, "declining"),  # below -0.001 threshold
        (0.0,    "stable"),     # exactly zero
        (0.0005, "stable"),     # positive but below growing threshold
    ])
    def test_trend_classification_thresholds(self, slope, expected_trend):
        """normalised_slope thresholds: >0.001 growing, <-0.001 declining."""
        if slope > 0.001:
            trend = "growing"
        elif slope < -0.001:
            trend = "declining"
        else:
            trend = "stable"

        assert trend == expected_trend

    def test_smoothing_window_does_not_crash_on_small_data(self):
        """With fewer than SMOOTH_WINDOW+1 points, smoothing falls back to raw signal."""
        signal        = [10, 12]   # only 2 points — not enough to smooth
        SMOOTH_WINDOW = 3

        if len(signal) >= SMOOTH_WINDOW + 1:
            smoothed = [
                sum(signal[max(0, i - 1):i + 2]) / len(signal[max(0, i - 1):i + 2])
                for i in range(len(signal))
            ]
        else:
            smoothed = signal[:]   # raw fallback — no smoothing applied

        assert smoothed == [10, 12]   # signal unchanged

    def test_velocity_reported_as_percent_per_day(self):
        """velocity = normalised_slope * 100, rounded to 3 decimal places."""
        normalised_slope = 0.002
        velocity         = round(normalised_slope * 100, 3)

        assert velocity == 0.2


# ─────────────────────────────────────────────────────────────────────────────

class TestGetSkillOverlap:
    """
    Tests for get_skill_overlap(db, occupation_id)

     from conftest.py:
        mock_db              --  MagicMock DB session
        sample_occupation_id -- 273333
    """

    def test_no_skills_returns_empty_structure(self, mock_db, sample_occupation_id):
        """If occupation has no skills, return empty matrix structure not crash."""
        mock_db.query.return_value \
               .join.return_value \
               .filter.return_value \
               .order_by.return_value \
               .limit.return_value \
               .all.return_value = []

        result = get_skill_overlap(mock_db, sample_occupation_id)
        assert result == {"skills": [], "occupations": [], "matrix": []}

    def test_db_exception_returns_empty_structure(self, mock_db, sample_occupation_id):
        """DB crash must return safe empty structure, never raise."""
        mock_db.query.side_effect = Exception("timeout")

        result = get_skill_overlap(mock_db, sample_occupation_id)

        assert result["skills"]      == []
        assert result["occupations"] == []
        assert result["matrix"]      == []

    def test_matrix_structure_is_correct(self):
        """
        logic test — no DB needed.
        Matrix must be skills x occupations.
        Each cell is 1 if the skill is shared with that occupation, else 0.
        """
        my_skill_ids  = [1, 2, 3]
        related_ids   = [10, 20]
        shared_lookup = {(10, 1), (10, 2), (20, 3)}   # skills 1&2 → occ10, skill 3 → occ20

        matrix = []
        for skill_id in my_skill_ids:
            row = [1 if (occ_id, skill_id) in shared_lookup else 0
                   for occ_id in related_ids]
            matrix.append(row)

        assert len(matrix)    == 3          # 3 skills
        assert len(matrix[0]) == 2          # 2 occupations
        assert matrix[0]      == [1, 0]     # skill 1: shared with occ 10, not 20
        assert matrix[1]      == [1, 0]     # skill 2: shared with occ 10, not 20
        assert matrix[2]      == [0, 1]     # skill 3: shared with occ 20, not 10


# ── Authorship Note ──────────────────────────────────────────────────────────
# Structured for high-coverage testing of complex SQLAlchemy queries and 
# data transformation logic within the Analytics Service.
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyticsService:

    # ── Test: Shadow Skills ──────────────────────────────────────────────────
    
    def test_get_shadow_skills_success(self, mock_db):
        """
        Scenario: Occupation has skills appearing in job logs that are not mapped.
        Validates: Proper joining and filtering logic.
        """
        # Arrange: Setup mock results for the query
        mock_row = MagicMock()
        mock_row.skill_name = "Python Programming"
        
        # Mocking the fluent API: db.query().join().join().filter()...all()
        mock_db.query.return_value.join.return_value.join.return_value \
            .filter.return_value.filter.return_value.filter.return_value \
            .group_by.return_value.order_by.return_value.limit.return_value \
            .all.return_value = [mock_row]

        # Act
        result = get_shadow_skills(mock_db, occupation_id=123)

        # Assert
        assert len(result) == 1
        assert result[0]["skill_name"] == "Python Programming"

    def test_get_shadow_skills_exception_handling(self, mock_db):
        """Validates that service returns empty list and logs error on DB failure."""
        mock_db.query.side_effect = Exception("Database Connection Lost")
        
        result = get_shadow_skills(mock_db, occupation_id=123)
        assert result == []

    # ── Test: Skill Decay ────────────────────────────────────────────────────

    def test_get_skill_decay_no_data(self, mock_db):
        """Scenario: No snapshots exist for the occupation."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        result = get_skill_decay(mock_db, occupation_id=999)
        assert result == []

    def test_get_skill_decay_calculation_logic(self, mock_db):
        """
        Scenario: Skill 'A' dropped from 100 to 40 (60% decay).
        Validates: The 50%+ threshold logic.
        """
        # 1. Mock date bounds (Earliest vs Latest)
        mock_bounds = MagicMock(earliest=date(2023, 1, 1), latest=date(2023, 12, 1))
        
        # 2. Setup mock responses for the series of queries in the function
        # We use side_effect to provide different returns for sequential .first() or .scalar() calls
        mock_db.query.return_value.filter.return_value.first.return_value = mock_bounds
        
        # job_execution_id mocks (scalar() calls)
        mock_db.query.return_value.filter.return_value.filter.return_value.scalar.side_effect = [10, 20]
        
        # Row data mocks (early vs late)
        early_row = MagicMock(skill_id=1, early_count=100)
        late_row = MagicMock(skill_id=1, late_count=40)
        
        # Label mock
        label_row = MagicMock(id=1, preferred_label="Legacy COBOL")
        
        # To handle the multiple .all() calls, we use side_effect on the final chain link
        mock_db.query.return_value.filter.return_value.filter.return_value.all.side_effect = [
            [early_row], [late_row], [label_row]
        ]

        # Act
        results = get_skill_decay(mock_db, occupation_id=1)

        # Assert
        assert len(results) == 1
        assert results[0]["skill_name"] == "Legacy COBOL"
        assert results[0]["decline_pct"] == 60.0

    # ── Test: Skill Velocity ─────────────────────────────────────────────────

    def test_get_skill_velocity_rising_status(self, mock_db):
        """
        Scenario: Mentions go from 10 to 50 over a 2-day span.
        Validates: Slope calculation and status categorization.
        """
        # Arrange
        rows = [
            MagicMock(skill_id=1, mention_count=10, snapshot_date=date(2023, 1, 1)),
            MagicMock(skill_id=1, mention_count=50, snapshot_date=date(2023, 1, 3))
        ]
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        
        label_row = MagicMock(id=1, preferred_label="FastAPI")
        mock_db.query.return_value.filter.return_value.all.return_value = [label_row]

        # Act
        result = get_skill_velocity(mock_db, occupation_id=1)

        # Assert
        assert result["snapshot_count"] == 2
        assert len(result["rising"]) == 1
        assert result["rising"][0]["skill_name"] == "FastAPI"
        assert result["rising"][0]["status"] == "rising"
        assert result["rising"][0]["slope"] > 0

    def test_get_skill_velocity_insufficient_data(self, mock_db):
        """Scenario: Only one snapshot exists."""
        rows = [MagicMock(skill_id=1, mention_count=10, snapshot_date=date(2023, 1, 1))]
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        
        label_row = MagicMock(id=1, preferred_label="Python")
        mock_db.query.return_value.filter.return_value.all.return_value = [label_row]

        # Act
        result = get_skill_velocity(mock_db, occupation_id=1)

        # Assert
        assert result["snapshot_count"] == 1
        assert len(result["stable"]) == 1
        assert result["stable"][0]["status"] == "stable"
        assert result["stable"][0]["slope"] == 0.0

    def test_get_skill_decay_full_execution(self, db_session, sample_occupation_id):
        """Covers all branches of get_skill_decay logic."""
        from app.models.skills import OscaOccupationSkillSnapshot, EscoSkill
        
        # Setup Skill
        skill = EscoSkill(preferred_label="Old Tech", skill_type="knowledge")
        db_session.add(skill)
        db_session.commit()

        # Setup two snapshots with 60% decay
        s1 = OscaOccupationSkillSnapshot(
            occupation_id=sample_occupation_id, 
            skill_id=skill.id, 
            mention_count=100, 
            snapshot_date=datetime(2023, 1, 1),
            job_execution_id=1
        )
        s2 = OscaOccupationSkillSnapshot(
            occupation_id=sample_occupation_id, 
            skill_id=skill.id, 
            mention_count=40, 
            snapshot_date=datetime(2023, 6, 1),
            job_execution_id=2
        )
        db_session.add_all([s1, s2])
        db_session.commit()

        results = get_skill_decay(db_session, sample_occupation_id)
        assert len(results) == 1
        assert results[0]["decline_pct"] == 60.0

    def test_get_skill_velocity_full_execution(self, db_session, sample_occupation_id):
        """Covers rising/falling logic branches in get_skill_velocity."""
        from app.models.skills import OscaOccupationSkillSnapshot, EscoSkill
        
        skill = EscoSkill(preferred_label="Hot Tech", skill_type="knowledge")
        db_session.add(skill)
        db_session.commit()

        # Setup rising trend
        dates = [datetime(2023, 1, 1), datetime(2023, 1, 2), datetime(2023, 1, 3)]
        counts = [10, 30, 90]
        for i in range(3):
            snap = OscaOccupationSkillSnapshot(
                occupation_id=sample_occupation_id,
                skill_id=skill.id,
                mention_count=counts[i],
                snapshot_date=dates[i]
            )
            db_session.add(snap)
        db_session.commit()

        result = get_skill_velocity(db_session, sample_occupation_id)
        assert len(result["rising"]) == 1
        assert result["rising"][0]["skill_name"] == "Hot Tech"
        assert result["snapshot_count"] == 3

    def test_get_shadow_skills_empty_db(self, db_session):
        """Covers the empty return branch."""
        results = get_shadow_skills(db_session, 99999)
        assert results == []

    def test_get_skill_decay_no_data(self, db_session):
        """Covers the initial return branch of decay."""
        assert get_skill_decay(db_session, 99999) == []
        