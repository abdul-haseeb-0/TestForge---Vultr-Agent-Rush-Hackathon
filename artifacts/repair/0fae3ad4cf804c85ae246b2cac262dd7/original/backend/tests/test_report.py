from app.qa import deterministic_report


def test_report_records_observed_console_errors():
    report = deterministic_report({"console_errors": ["TypeError: cannot read property"], "failed_requests": [], "broken_links": [], "page_error": None})
    assert len(report["findings"]) == 1
    assert "TypeError" in report["findings"][0]["evidence"]


def test_browser_cancellation_is_not_a_confirmed_finding():
    report = deterministic_report({
        "console_errors": [],
        "failed_requests": [],  # ERR_ABORTED / blocked-by-client are filtered at collection time
        "broken_links": [],
        "inconclusive_links": [{"href": "https://example.com/", "reason": "timeout"}],
        "page_error": None,
    })
    assert report["findings"] == []
    assert report["score"] == 0  # no page was visited, so no quality score can be claimed


def test_third_party_http_error_is_informational_not_a_defect():
    report = deterministic_report({
        "console_errors": [], "failed_requests": [], "broken_links": [], "page_error": None,
        "http_errors": [{"url": "https://accounts.google.com/", "status": 401, "same_origin": False, "resource_type": "document"}],
    })
    assert len(report["findings"]) == 1
    assert report["findings"][0]["severity"] == "info"
    assert report["findings"][0]["category"] == "access"
    assert report["score"] == 0  # no page coverage means score is not established


def test_same_origin_server_error_is_reported():
    report = deterministic_report({
        "console_errors": [], "failed_requests": [], "broken_links": [], "page_error": None,
        "http_errors": [{"url": "https://example.com/api", "status": 500, "same_origin": True, "resource_type": "fetch"}],
    })
    assert report["findings"][0]["severity"] == "medium"
    assert report["findings"][0]["category"] == "http"


def test_duplicate_evidence_is_deduplicated():
    report = deterministic_report({
        "console_errors": ["TypeError: failed", "TypeError: failed"],
        "failed_requests": [], "broken_links": [], "page_error": None,
    })
    assert len(report["findings"]) == 1


def test_empty_evidence_without_page_coverage_has_no_score():
    report = deterministic_report({"console_errors": [], "failed_requests": [], "broken_links": [], "page_error": None})
    assert report["score"] == 0
    assert not report["findings"]


def test_clean_visited_page_gets_full_deterministic_score():
    report = deterministic_report({"pages": [{"url": "https://example.com", "screenshot": "page-01-home.png"}], "coverage": {"pages_visited": 1, "forms_observed": 0, "crawl_truncated": False}, "console_errors": [], "http_errors": [], "failed_requests": [], "broken_links": [], "page_error": None})
    assert report["score"] == 100


def test_truncated_crawl_caps_score_to_avoid_claiming_full_coverage():
    report = deterministic_report({"pages": [{"url": "https://example.com", "screenshot": "page-01-home.png"}], "coverage": {"pages_visited": 3, "forms_observed": 0, "crawl_truncated": True}, "console_errors": [], "http_errors": [], "failed_requests": [], "broken_links": [], "page_error": None})
    assert report["score"] == 85


def test_repeated_third_party_403_responses_are_grouped_as_inconclusive():
    report = deterministic_report({
        "console_errors": [], "failed_requests": [], "broken_links": [], "page_error": None,
        "http_errors": [
            {"url": "https://cdn.example.net/a.js", "status": 403, "same_origin": False, "resource_type": "script"},
            {"url": "https://cdn.example.net/b.js", "status": 403, "same_origin": False, "resource_type": "script"},
        ],
    })
    assert len(report["findings"]) == 1
    assert report["findings"][0]["severity"] == "info"
    assert "2 occurrence" in report["findings"][0]["description"]


def test_failed_crud_workflow_step_is_reported_with_evidence():
    report = deterministic_report({
        "pages": [{"url": "https://example.com/items", "screenshot": "page-01-items.png"}],
        "coverage": {"pages_visited": 1, "forms_observed": 1, "crawl_truncated": False},
        "console_errors": [], "http_errors": [], "failed_requests": [], "broken_links": [],
        "workflow_checks": [{"step": 4, "action": "assert_text_absent", "status": "failed", "error": "Unexpected text is still present", "screenshot": "workflow-04.png"}],
        "page_error": None,
    })
    assert len(report["findings"]) == 1
    assert report["findings"][0]["category"] == "workflow"
    assert report["findings"][0]["severity"] == "high"
