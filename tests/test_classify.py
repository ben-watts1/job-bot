from classify import classify_job


def test_gtm_precedence_over_eng():
    assert classify_job("Sales Engineer") == "ignore"


def test_engineering_match():
    assert classify_job("Senior Backend Engineer", "Platform") == "eng"


def test_product_match():
    assert classify_job("Technical Product Manager", "Core Product") == "product"


def test_ignore_unknown():
    assert classify_job("Chief of Staff", "Operations") == "ignore"


def test_growth_marketing_ignore():
    assert classify_job("Growth Manager", "Marketing") == "ignore"
