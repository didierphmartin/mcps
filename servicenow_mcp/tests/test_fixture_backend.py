import hashlib
import json
import re

import pytest

from conftest import A, B, ROOT
from fixture_backend import FixtureBackend


def test_oldest_open_task_in_group_with_prefix(data):
    b = FixtureBackend(data)
    assert b.find_oldest_open_task("SynergyAI", "synergyai:")["number"] == "SCTASK0000001"
    assert b.find_oldest_open_task("SynergyAI", "synergyai:git")["number"] == "SCTASK0000002"
    assert b.find_oldest_open_task("SynergyAI", "synergyai:none") is None


def test_normalized_task_by_number_and_sys_id(data):
    b = FixtureBackend(data)
    t = b.get_task("SCTASK0000001")
    assert t["sys_id"] == A
    assert t["state"] == 1 and t["active"] is True
    assert t["request_item_number"] == "RITM0000001"
    assert t["catalog_item"] == "Okta password reset"
    assert t["requested_for"] == "jane.doe"
    assert b.get_task(B)["number"] == "SCTASK0000002"
    assert b.get_task("SCTASK9999999") is None


def test_answers_include_label_rows(data):
    b = FixtureBackend(data)
    assert len(b.get_answers("RITM0000001")) == 2
    assert b.get_answers("RITM0000002") == []
    assert b.get_answers("RITM-missing") == []


def test_updates_state_group_and_notes(data):
    b = FixtureBackend(data)
    desk = b.find_group_sys_id("Service Desk")
    assert re.fullmatch(r"[0-9a-f]{32}", desk)
    assert b.find_group_sys_id("Nobody") is None
    b.update_task(A, {"state": 3, "work_notes": "done", "close_notes": "closed"})
    b.update_task(A, {"assignment_group": desk})
    t = b.get_task(A)
    assert t["state"] == 3 and t["active"] is False
    assert t["assignment_group"] == "Service Desk"
    assert b.task_notes(A) == ["done"]


def test_mock_fixture_file_loads():
    assert FixtureBackend.from_file(ROOT / "fixtures" / "mock.json").find_oldest_open_task("SynergyAI", "synergyai:")


class TestState:
    """The mock remembers its changes across HTTP requests (one backend per request)."""

    @pytest.fixture(autouse=True)
    def files(self, tmp_path, data):
        self.fixture = tmp_path / "mock.json"
        self.state = tmp_path / "var" / "mock-state.json"
        self.fixture.write_text(json.dumps(data))

    def request(self):
        return FixtureBackend.with_state(self.fixture, self.state)

    def test_a_completed_task_stays_completed_on_the_next_request(self):
        first = self.request().find_oldest_open_task("SynergyAI", "synergyai:")
        assert first["number"] == "SCTASK0000001"
        self.request().update_task(first["sys_id"], {"state": 3, "close_notes": "done"})
        assert self.request().find_oldest_open_task("SynergyAI", "synergyai:")["number"] == "SCTASK0000002"
        assert self.state.is_file()

    def test_notes_and_hand_back_persist(self):
        self.request().update_task(A, {"work_notes": "step 1"})
        self.request().update_task(A, {"work_notes": "step 2",
                                       "assignment_group": hashlib.md5(b"Service Desk").hexdigest()})
        b = self.request()
        assert b.task_notes(A) == ["step 1", "step 2"]
        assert b.find_oldest_open_task("SynergyAI", "synergyai:")["number"] == "SCTASK0000002"

    def test_reads_do_not_create_the_state_file(self):
        self.request().find_oldest_open_task("SynergyAI", "synergyai:")
        assert not self.state.exists()

    def test_reset_goes_back_to_the_fixture(self):
        self.request().update_task(A, {"state": 3})
        FixtureBackend.reset_state(self.state)
        assert not self.state.exists()
        assert self.request().find_oldest_open_task("SynergyAI", "synergyai:")["number"] == "SCTASK0000001"

    def test_refresh_sees_another_requests_changes(self):
        waiting = self.request()                       # a wait opened before the claim
        self.request().update_task(A, {"state": 2})
        assert waiting.find_oldest_open_task("SynergyAI", "synergyai:")["number"] == "SCTASK0000001"
        waiting.refresh()
        assert waiting.find_oldest_open_task("SynergyAI", "synergyai:")["number"] == "SCTASK0000002"

    def test_refresh_after_reset_goes_back_to_the_fixture(self):
        self.request().update_task(A, {"state": 3})
        waiting = self.request()
        FixtureBackend.reset_state(self.state)
        waiting.refresh()
        assert waiting.find_oldest_open_task("SynergyAI", "synergyai:")["number"] == "SCTASK0000001"
