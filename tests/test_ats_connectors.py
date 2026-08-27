"""Fixture-based golden tests for the Greenhouse/Lever/Ashby catalog
connectors (skills/scrape_job_boards/{greenhouse,lever,ashby}.py).

Every HTTP call is mocked -- these tests never touch the real network, per
the project's CI testing philosophy (externals mocked in CI, live smoke
tests done manually). Real API shapes were verified live against
boards-api.greenhouse.io, api.lever.co, and api.ashbyhq.com before writing
these fixtures; see each connector module's docstring for the endpoints.

Covers: pagination is a non-issue for these single-response APIs, but
per the Phase 1 test gate we still verify: a normal populated board, an
empty board (0 postings -- valid, not an error), a dead/unknown token
(404), a malformed JSON response, and dedup correctness on a second sync
of the same board.
"""

from unittest.mock import MagicMock, patch

from db import repository as repo
from skills.scrape_job_boards import ashby, greenhouse, lever


def _fake_response(status_code=200, json_data=None, raise_json_error=False):
    resp = MagicMock()
    resp.status_code = status_code
    if raise_json_error:
        resp.json.side_effect = ValueError("not valid json")
    else:
        resp.json.return_value = json_data
    return resp


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------

GH_JOBS_FIXTURE = {
    "jobs": [
        {
            "id": 111,
            "title": "Backend Engineer",
            "company_name": "Acme Co",
            "location": {"name": "Remote"},
            "departments": [{"name": "Engineering"}],
            "content": "<p>Build things &amp; ship them.</p>",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/111",
            "first_published": "2026-01-01T00:00:00-05:00",
        },
        {
            "id": 222,
            "title": "Frontend Engineer",
            "company_name": "Acme Co",
            "location": {"name": "NYC"},
            "departments": [],
            "content": "",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/222",
            "first_published": None,
        },
    ]
}


def test_greenhouse_sync_normal_board():
    with patch("skills.scrape_job_boards.greenhouse.requests.get",
               return_value=_fake_response(200, GH_JOBS_FIXTURE)):
        result = greenhouse.sync_company("acme")

    assert result["status"] == "ok"
    assert result["added"] == 2
    assert result["skipped"] == 0

    company = repo.get_or_create_company("Acme Co", ats_type="greenhouse", ats_token="acme")
    jobs = repo.get_jobs(company["id"])
    assert len(jobs) == 2
    titles = {j["title"] for j in jobs}
    assert titles == {"Backend Engineer", "Frontend Engineer"}
    # HTML entities/tags stripped from jd_text
    backend = next(j for j in jobs if j["title"] == "Backend Engineer")
    assert "<p>" not in backend["jd_text"]
    assert "Build things & ship them." in backend["jd_text"]
    # last_scraped_at stamped by sync_company (company was fetched again
    # inside sync_company via get_or_create_company, then stamped after
    # the job loop -- the `company` dict captured here, post-sync, must
    # reflect that stamp).
    assert company["last_scraped_at"] is not None


def test_greenhouse_sync_empty_board_is_not_an_error():
    with patch("skills.scrape_job_boards.greenhouse.requests.get",
               return_value=_fake_response(200, {"jobs": []})):
        result = greenhouse.sync_company("empty-board-co")

    assert result["status"] == "ok"
    assert result["added"] == 0
    assert result["error"] is None


def test_greenhouse_sync_dead_token_404():
    with patch("skills.scrape_job_boards.greenhouse.requests.get",
               return_value=_fake_response(404)):
        result = greenhouse.sync_company("nonexistent")

    assert result["status"] == "not_found"
    assert result["added"] == 0
    assert result["error"] is not None


def test_greenhouse_sync_malformed_json():
    with patch("skills.scrape_job_boards.greenhouse.requests.get",
               return_value=_fake_response(200, raise_json_error=True)):
        result = greenhouse.sync_company("bad-json-co")

    assert result["status"] == "error"
    assert result["added"] == 0


def test_greenhouse_sync_dedups_on_rerun():
    with patch("skills.scrape_job_boards.greenhouse.requests.get",
               return_value=_fake_response(200, GH_JOBS_FIXTURE)):
        first = greenhouse.sync_company("acme-dedup")
        second = greenhouse.sync_company("acme-dedup")

    assert first["added"] == 2
    assert second["added"] == 0
    assert second["skipped"] == 2

    company = repo.get_or_create_company("Acme Co", ats_type="greenhouse", ats_token="acme-dedup")
    assert len(repo.get_jobs(company["id"])) == 2  # not 4


def test_greenhouse_sync_closes_jobs_no_longer_on_the_board():
    """A job present in an earlier sync but absent from a later one (the
    company filled/pulled it) must be marked is_open=False, never
    silently left looking open forever."""
    with patch("skills.scrape_job_boards.greenhouse.requests.get",
               return_value=_fake_response(200, GH_JOBS_FIXTURE)):
        greenhouse.sync_company("acme-close-test")

    # Second sync: the board now only lists the Backend Engineer role --
    # Frontend Engineer (id 222) has been filled/removed.
    shrunk_fixture = {"jobs": [GH_JOBS_FIXTURE["jobs"][0]]}
    with patch("skills.scrape_job_boards.greenhouse.requests.get",
               return_value=_fake_response(200, shrunk_fixture)):
        greenhouse.sync_company("acme-close-test")

    company = repo.get_or_create_company("Acme Co", ats_type="greenhouse", ats_token="acme-close-test")
    jobs = {j["title"]: j for j in repo.get_jobs(company["id"])}
    assert jobs["Backend Engineer"]["is_open"] is True
    assert jobs["Frontend Engineer"]["is_open"] is False

    open_jobs = repo.get_jobs(company["id"], open_only=True)
    assert len(open_jobs) == 1
    assert open_jobs[0]["title"] == "Backend Engineer"


def test_greenhouse_sync_skips_malformed_job_entry():
    fixture = {"jobs": [{"id": None, "title": "No ID"}, GH_JOBS_FIXTURE["jobs"][0]]}
    with patch("skills.scrape_job_boards.greenhouse.requests.get",
               return_value=_fake_response(200, fixture)):
        result = greenhouse.sync_company("malformed-entry-co")

    assert result["added"] == 1
    assert result["skipped"] == 1


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------

LEVER_JOBS_FIXTURE = [
    {
        "id": "abc-123",
        "text": "Backend Engineer",
        "categories": {"department": "Engineering", "location": "Remote"},
        "descriptionPlain": "Build the backend.",
        "hostedUrl": "https://jobs.lever.co/acme/abc-123",
        "createdAt": 1700000000000,  # milliseconds
    },
    {
        "id": "def-456",
        "text": "Sales Rep",
        "categories": {"team": "Sales"},
        "descriptionPlain": "Sell things.",
        "applyUrl": "https://jobs.lever.co/acme/def-456/apply",
        "createdAt": None,
    },
]


def test_lever_sync_normal_board():
    with patch("skills.scrape_job_boards.lever.requests.get",
               return_value=_fake_response(200, LEVER_JOBS_FIXTURE)):
        result = lever.sync_company("acme-lever")

    assert result["status"] == "ok"
    assert result["added"] == 2

    company = repo.get_or_create_company("Acme-lever", ats_type="lever", ats_token="acme-lever")
    jobs = repo.get_jobs(company["id"])
    assert len(jobs) == 2
    backend = next(j for j in jobs if j["title"] == "Backend Engineer")
    assert backend["department"] == "Engineering"
    assert backend["posted_at"] is not None  # ms epoch parsed correctly
    sales = next(j for j in jobs if j["title"] == "Sales Rep")
    assert sales["department"] == "Sales"  # falls back to 'team'
    assert sales["posted_at"] is None  # None createdAt handled gracefully


def test_lever_sync_empty_array_is_not_an_error():
    """A real Lever site with zero open postings returns 200 + `[]`, not
    a 404 -- must be treated as a valid, empty sync, not a failure."""
    with patch("skills.scrape_job_boards.lever.requests.get",
               return_value=_fake_response(200, [])):
        result = lever.sync_company("no-openings-co")

    assert result["status"] == "ok"
    assert result["added"] == 0
    assert result["error"] is None


def test_lever_sync_dead_token_404():
    with patch("skills.scrape_job_boards.lever.requests.get",
               return_value=_fake_response(404)):
        result = lever.sync_company("nonexistent-lever")

    assert result["status"] == "not_found"


def test_lever_sync_malformed_response_not_a_list():
    with patch("skills.scrape_job_boards.lever.requests.get",
               return_value=_fake_response(200, {"unexpected": "shape"})):
        result = lever.sync_company("bad-shape-co")

    assert result["status"] == "error"


def test_lever_sync_dedups_on_rerun():
    with patch("skills.scrape_job_boards.lever.requests.get",
               return_value=_fake_response(200, LEVER_JOBS_FIXTURE)):
        first = lever.sync_company("acme-lever-dedup")
        second = lever.sync_company("acme-lever-dedup")

    assert first["added"] == 2
    assert second["added"] == 0

    company = repo.get_or_create_company("Acme-lever-dedup", ats_type="lever", ats_token="acme-lever-dedup")
    assert len(repo.get_jobs(company["id"])) == 2


# ---------------------------------------------------------------------------
# Ashby
# ---------------------------------------------------------------------------

ASHBY_JOBS_FIXTURE = {
    "jobs": [
        {
            "id": "job-1",
            "title": "Backend Engineer",
            "department": "Engineering",
            "team": "Platform",
            "location": "Remote",
            "isListed": True,
            "descriptionPlain": "Build the platform.",
            "jobUrl": "https://jobs.ashbyhq.com/acme/job-1",
            "publishedAt": "2026-01-01T00:00:00.000+00:00",
        },
        {
            "id": "job-2",
            "title": "Unlisted Role",
            "department": "Ops",
            "location": "NYC",
            "isListed": False,  # only reachable via direct link -- must be filtered out
            "descriptionPlain": "Hidden role.",
            "jobUrl": "https://jobs.ashbyhq.com/acme/job-2",
            "publishedAt": "2026-01-01T00:00:00.000+00:00",
        },
    ]
}


def test_ashby_sync_normal_board_filters_unlisted():
    with patch("skills.scrape_job_boards.ashby.requests.get",
               return_value=_fake_response(200, ASHBY_JOBS_FIXTURE)):
        result = ashby.sync_company("acme-ashby")

    assert result["status"] == "ok"
    assert result["added"] == 1  # the isListed=False job must NOT be added

    company = repo.get_or_create_company("Acme-ashby", ats_type="ashby", ats_token="acme-ashby")
    jobs = repo.get_jobs(company["id"])
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Backend Engineer"


def test_ashby_sync_empty_board_is_not_an_error():
    with patch("skills.scrape_job_boards.ashby.requests.get",
               return_value=_fake_response(200, {"jobs": []})):
        result = ashby.sync_company("empty-ashby-co")

    assert result["status"] == "ok"
    assert result["added"] == 0


def test_ashby_sync_dead_token_404():
    with patch("skills.scrape_job_boards.ashby.requests.get",
               return_value=_fake_response(404)):
        result = ashby.sync_company("nonexistent-ashby")

    assert result["status"] == "not_found"


def test_ashby_sync_malformed_json():
    with patch("skills.scrape_job_boards.ashby.requests.get",
               return_value=_fake_response(200, raise_json_error=True)):
        result = ashby.sync_company("bad-json-ashby-co")

    assert result["status"] == "error"


def test_ashby_sync_dedups_on_rerun():
    with patch("skills.scrape_job_boards.ashby.requests.get",
               return_value=_fake_response(200, ASHBY_JOBS_FIXTURE)):
        first = ashby.sync_company("acme-ashby-dedup")
        second = ashby.sync_company("acme-ashby-dedup")

    assert first["added"] == 1
    assert second["added"] == 0

    company = repo.get_or_create_company("Acme-ashby-dedup", ats_type="ashby", ats_token="acme-ashby-dedup")
    assert len(repo.get_jobs(company["id"])) == 1


# ---------------------------------------------------------------------------
# run() -- batch behavior: one bad token never stops the rest of the batch
# ---------------------------------------------------------------------------

def test_greenhouse_run_continues_past_a_failed_token():
    def fake_get(url, params=None, timeout=None):
        if "dead-token" in url:
            return _fake_response(404)
        return _fake_response(200, GH_JOBS_FIXTURE)

    with patch("skills.scrape_job_boards.greenhouse.requests.get", side_effect=fake_get):
        summary = greenhouse.run(["dead-token", "acme-batch"])

    statuses = {r["token"]: r["status"] for r in summary["results"]}
    assert statuses["dead-token"] == "not_found"
    assert statuses["acme-batch"] == "ok"
    assert summary["total_added"] == 2
