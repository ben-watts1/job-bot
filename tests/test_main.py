from main import is_technical_job, title_matches_keywords


def test_title_matches_software_developer():
    assert title_matches_keywords("Software Developer")


def test_title_matches_data_scientist():
    assert title_matches_keywords("Data Scientist")


def test_title_matches_security_analyst():
    assert title_matches_keywords("Security Analyst")


def test_title_matches_platform_architect():
    assert title_matches_keywords("Platform Architect")


def test_title_matches_site_reliability_engineer():
    assert title_matches_keywords("Site Reliability Engineer")


def test_is_technical_job_uses_title_filter():
    job = {
        "title": "Software Developer",
        "team_name": "Sales",
        "parent_team_name": "Operations",
    }
    assert is_technical_job(job)
