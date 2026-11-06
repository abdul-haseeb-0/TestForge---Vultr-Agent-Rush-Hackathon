from app.main import CreateRun


def test_create_run_accepts_explicit_crud_workflow():
    run = CreateRun.model_validate({
        "target_url": "https://example.com",
        "depth": "deep",
        "workflow": [
            {"action": "navigate", "value": "/items"},
            {"action": "fill", "selector": "input[name='name']", "value": "QA record"},
            {"action": "assert_text_absent", "selector": "body", "value": "QA record"},
        ],
    })
    assert len(run.workflow) == 3
    assert run.workflow[-1].action == "assert_text_absent"


def test_create_run_rejects_unknown_workflow_actions():
    try:
        CreateRun.model_validate({"target_url": "https://example.com", "workflow": [{"action": "execute_shell"}]})
    except Exception:
        return
    raise AssertionError("Unknown workflow actions must be rejected")
