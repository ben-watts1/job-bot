from ashby import AshbyClient


def test_derive_slug_from_canonical_url():
    c = AshbyClient()
    assert c.derive_org_slug_from_url("https://jobs.ashbyhq.com/acme") == "acme"


def test_derive_slug_with_extra_path():
    c = AshbyClient()
    assert c.derive_org_slug_from_url("https://jobs.ashbyhq.com/acme/some/path") == "acme"


def test_normalize_board_url():
    c = AshbyClient()
    assert c.normalize_board_url("jobs.ashbyhq.com/Acme") == "https://jobs.ashbyhq.com/acme"
