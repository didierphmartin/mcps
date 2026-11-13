import json

import pytest

from config import Config
from conftest import A, B
from errors import ConnectorError
from fixture_backend import FixtureBackend
from jobs import JobsToolset


@pytest.fixture
def backend(data):
    return FixtureBackend(data)


@pytest.fixture
def tools(backend):
    return JobsToolset(Config.mock(), backend)


def fails(tools, tool, args):
    with pytest.raises(ConnectorError) as e:
        tools.call(tool, args)
    return f"{e.value.code}|{e.value}"


def waiting(backend, on_sleep=None):
    """A toolset whose sleeps are recorded, not slept, on a fake clock that only sleeping moves."""
    sleeps, clock = [], [0.0]

    def sleep(s):
        sleeps.append(s)
        clock[0] += s
        if on_sleep:
            on_sleep(len(sleeps))
    return JobsToolset(Config.mock(), backend, sleep, lambda: clock[0]), sleeps


class SlowEmptyBackend:
    """No task ever; each check costs `cost` seconds on the shared clock; counts refreshes."""
    def __init__(self, clock, cost=0.0):
        self.clock, self.cost, self.refreshes = clock, cost, 0

    def refresh(self):
        self.refreshes += 1

    def find_oldest_open_task(self, *a):
        self.clock[0] += self.cost
        return None


def test_describe_item(tools):
    r = tools.call("describe_item", {"key": "okta-reset"})
    assert r["environment"] == "dev"
    assert r["item"]["version"] == 1
    assert r["item"]["name"] == "Okta password reset"
    assert r["item"]["variables"] == [{"name": "user_email", "type": "6", "mandatory": True},
                                      {"name": "reason", "type": "6", "mandatory": False}]
    assert tools.call("describe_item", {"key": "nope"})["item"] is None
    assert fails(tools, "describe_item", {"key": "Bad^Key"}).startswith("bad_argument|")
    assert fails(tools, "describe_item", {}).startswith("bad_argument|")


def test_definitions_list_the_seven_tools(tools):
    assert [t["name"] for t in tools.tools()] == ["poll_jobs", "wait_for_jobs", "claim_job", "add_note", "complete_job",
                                                  "hand_back", "describe_item"]
    for t in tools.tools():
        assert t["inputSchema"]["additionalProperties"] is False


def test_wait_is_ready_at_once_when_a_job_exists(backend):
    t, sleeps = waiting(backend)
    assert t.call("wait_for_jobs", {}) == {"status": "ready", "via": "poll"}
    assert sleeps == []


def test_wait_becomes_ready_when_a_job_appears(backend):
    backend.update_task(A, {"state": 2})
    backend.update_task(B, {"state": 2})
    t, sleeps = waiting(backend, lambda n: n == 3 and backend.update_task(A, {"state": 1}))
    assert t.call("wait_for_jobs", {}) == {"status": "ready", "via": "poll"}
    assert sleeps == [5, 5, 5]


def test_wait_ignores_claimed_tasks_and_times_out(backend):
    backend.update_task(A, {"state": 2})
    backend.update_task(B, {"state": 3})
    t, sleeps = waiting(backend)
    assert t.call("wait_for_jobs", {}) == {"status": "timeout", "via": "poll"}
    assert sleeps == [5] * 24   # checks at 0, 5, ..., 120 s: 25 checks, 24 sleeps


def test_wait_filters_by_tag(backend):
    t, _ = waiting(backend)
    assert t.call("wait_for_jobs", {"tag": "git-access"})["status"] == "ready"
    assert t.call("wait_for_jobs", {"tag": "unknown"})["status"] == "timeout"


def test_wait_rejects_bad_tag_without_sleeping(backend):
    t, sleeps = waiting(backend)
    assert fails(t, "wait_for_jobs", {"tag": "x^y"}).startswith("bad_argument|")
    assert sleeps == []


def test_wait_window_is_measured_on_the_clock_including_check_latency():
    clock, sleeps = [0.0], []
    b = SlowEmptyBackend(clock, cost=3.0)
    t = JobsToolset(Config.mock(), b, lambda s: (sleeps.append(s), clock.__setitem__(0, clock[0] + s)), lambda: clock[0])
    assert t.call("wait_for_jobs", {}) == {"status": "timeout", "via": "poll"}
    assert clock[0] <= 123.0    # window + at most the last check's latency
    assert 0 < len(sleeps) < 24


def test_refresh_runs_before_every_check():
    clock = [0.0]
    b = SlowEmptyBackend(clock)
    t = JobsToolset(Config.mock(), b, lambda s: clock.__setitem__(0, clock[0] + s), lambda: clock[0])
    assert t.call("wait_for_jobs", {})["status"] == "timeout"
    assert b.refreshes == 25


def test_backend_error_during_wait_is_a_tool_error():
    class Down(SlowEmptyBackend):
        def find_oldest_open_task(self, *a):
            raise ConnectorError("servicenow_error", "down")
    t = JobsToolset(Config.mock(), Down([0.0]), lambda s: None, lambda: 0.0)
    with pytest.raises(ConnectorError, match="down"):
        t.call("wait_for_jobs", {})


def test_poll_returns_oldest_job_with_answers(tools):
    job = tools.call("poll_jobs", {})["job"]
    assert job["number"] == "SCTASK0000001"
    assert job["tag"] == "okta-reset"
    assert job["state"] == "open"
    assert job["request_item"] == "RITM0000001"
    assert job["answers"] == {"email": {"label": "Email", "value": "jane@acme.com"}}


def test_job_carries_version_and_catalog_item_id(tools):
    job = tools.call("poll_jobs", {"tag": "okta-reset"})["job"]
    assert job["version"] == 1
    assert job["catalog_item_id"] == "c0ffee00000000000000000000000101"


@pytest.mark.parametrize("stamp", ["", "okta-reset@x", "git-access@3", "okta-reset@", "okta-reset@1x"])
def test_version_is_none_when_stamp_missing_or_foreign(data, stamp):
    data["tasks"][1]["correlation_id"] = stamp
    t = JobsToolset(Config.mock(), FixtureBackend(data))
    assert t.call("poll_jobs", {"tag": "okta-reset"})["job"]["version"] is None


def test_exact_tag_does_not_match_longer_tag(data):
    data["tasks"] = [{"sys_id": "d" * 32, "number": "SCTASK0000009", "state": 1, "active": True,
                      "assignment_group": "SynergyAI", "correlation_display": "synergyai:okta-reset-2",
                      "short_description": "Longer tag", "created": "2026-10-01T08:00:00Z", "request_item": "RITM0000001",
                      "correlation_id": "okta-reset-2@1"}]
    t = JobsToolset(Config.mock(), FixtureBackend(data))
    assert t.call("poll_jobs", {"tag": "okta-reset"})["job"] is None


def test_poll_by_tag_and_empty(tools):
    assert tools.call("poll_jobs", {"tag": "git-access"})["job"]["number"] == "SCTASK0000002"
    assert tools.call("poll_jobs", {"tag": "unknown"})["job"] is None


def test_empty_answers_encode_as_object(tools):
    job = tools.call("poll_jobs", {"tag": "git-access"})["job"]
    assert json.dumps(job["answers"]) == "{}"


def test_injection_in_arguments_is_rejected(tools):
    assert fails(tools, "poll_jobs", {"tag": "x^ORactive=true"}).startswith("bad_argument|")
    assert fails(tools, "claim_job", {"task": "SCTASK1^ORnumber=SCTASK2"}).startswith("bad_argument|")
    tools.call("claim_job", {"task": "SCTASK0000001"})
    assert fails(tools, "hand_back", {"task": "SCTASK0000001", "group": "Desk^ORname=X", "reason": "r"}).startswith(
        "bad_argument|")


def test_claim_then_complete(tools, backend):
    assert tools.call("claim_job", {"task": "SCTASK0000001"})["state"] == "work_in_progress"
    done = tools.call("complete_job", {"task": "SCTASK0000001", "notes": "Password reset."})
    assert done == {"task": A, "number": "SCTASK0000001", "state": "closed_complete"}
    assert backend.task_notes(A) == ["Claimed by SynergyAI.", "Completed by SynergyAI."]
    assert tools.call("poll_jobs", {})["job"]["number"] == "SCTASK0000002"


def test_claim_after_someone_else_closed_it(tools, backend):
    backend.update_task(A, {"state": 3})
    msg = fails(tools, "claim_job", {"task": "SCTASK0000001"})
    assert msg.startswith("not_claimable|")
    assert "closed_complete" in msg


def test_complete_needs_a_claim(tools):
    assert fails(tools, "complete_job", {"task": "SCTASK0000001", "notes": "x"}).startswith("not_claimed|")


def test_add_note(tools):
    r = tools.call("add_note", {"task": A, "text": "Looking up the user."})
    assert r == {"task": A, "number": "SCTASK0000001", "noted": True}
    assert fails(tools, "add_note", {"task": "SCTASK0000001", "text": "  "}).startswith("bad_argument|")
    assert fails(tools, "add_note", {"task": "SCTASK0000001", "text": "x" * 4001}).startswith("bad_argument|")


def test_hand_back(tools, backend):
    r = tools.call("hand_back", {"task": "SCTASK0000001", "group": "Service Desk", "reason": "User not found in Okta"})
    assert r == {"task": A, "number": "SCTASK0000001", "state": "open", "group": "Service Desk"}
    t = backend.get_task("SCTASK0000001")
    assert t["assignment_group"] == "Service Desk"
    assert t["state"] == 1
    assert backend.task_notes(A) == ["Handed back by SynergyAI: User not found in Okta"]
    assert fails(tools, "hand_back", {"task": "SCTASK0000002", "group": "Nobody", "reason": "r"}).startswith(
        "group_not_found|")


def test_tasks_outside_synergyai_are_not_found(tools):
    assert fails(tools, "claim_job", {"task": "SCTASK0000003"}).startswith("task_not_found|")
    assert fails(tools, "claim_job", {"task": "SCTASK0009999"}).startswith("task_not_found|")
    assert fails(tools, "claim_job", {}).startswith("bad_argument|")
    assert fails(tools, "nope", {}).startswith("bad_argument|")


@pytest.mark.parametrize("group", ["javascript:gs.getUser()", "JavaScript:x", "SynergyAI", "synergyai", "Desk;drop"])
def test_hand_back_refuses_code_and_its_own_group(tools, group):
    assert fails(tools, "hand_back", {"task": "SCTASK0000001", "group": group, "reason": "r"}).startswith("bad_argument|")


def test_hand_back_accepts_accented_group_names(tools, backend, data):
    data["groups"].append("Équipe Identité")
    t = JobsToolset(Config.mock(), FixtureBackend(data))
    assert t.call("hand_back", {"task": "SCTASK0000001", "group": "Équipe Identité", "reason": "r"})["group"] == "Équipe Identité"


def test_closed_tasks_cannot_be_handed_back_or_noted(tools, backend):
    tools.call("claim_job", {"task": "SCTASK0000001"})
    tools.call("complete_job", {"task": "SCTASK0000001", "notes": "done"})
    msg = fails(tools, "hand_back", {"task": "SCTASK0000001", "group": "Service Desk", "reason": "r"})
    assert msg.startswith("not_claimable|") and "closed_complete" in msg
    assert fails(tools, "add_note", {"task": "SCTASK0000001", "text": "late"}).startswith("not_claimable|")
    assert backend.get_task("SCTASK0000001")["state"] == 3


def test_tag_filter_is_an_exact_match(tools):
    assert tools.call("poll_jobs", {"tag": "okta"})["job"] is None
    assert tools.call("poll_jobs", {"tag": "okta-reset"})["job"]["number"] == "SCTASK0000001"
