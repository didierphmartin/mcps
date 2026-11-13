import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

A, B, C = "a" * 32, "b" * 32, "c" * 32

DATA = {
    "groups": ["SynergyAI", "Service Desk"],
    "tasks": [
        {"sys_id": B, "number": "SCTASK0000002", "state": 1, "active": True, "assignment_group": "SynergyAI",
         "correlation_display": "synergyai:git-access", "short_description": "Grant Git",
         "created": "2026-10-01T10:00:00Z", "request_item": "RITM0000002"},
        {"sys_id": A, "number": "SCTASK0000001", "state": 1, "active": True, "assignment_group": "SynergyAI",
         "correlation_display": "synergyai:okta-reset", "short_description": "Reset Okta",
         "created": "2026-10-01T09:00:00Z", "request_item": "RITM0000001", "correlation_id": "okta-reset@1"},
        {"sys_id": C, "number": "SCTASK0000003", "state": 1, "active": True, "assignment_group": "Service Desk",
         "correlation_display": "", "short_description": "Human work", "created": "2026-09-30T09:00:00Z",
         "request_item": "RITM0000001"},
    ],
    "items": {"okta-reset": {"sys_id": "c0ffee00000000000000000000000101", "name": "Okta password reset",
                             "variables": [{"name": "synergyai_automation", "type": "6", "mandatory": False,
                                            "default_value": "okta-reset@1"},
                                           {"name": "user_email", "type": "6", "mandatory": True},
                                           {"name": "reason", "type": "6", "mandatory": False}]}},
    "request_items": {
        "RITM0000001": {"catalog_item": "Okta password reset", "catalog_item_id": "c0ffee00000000000000000000000101",
                        "requested_for": "jane.doe",
                        "answers": [{"name": "", "label": "Intro", "value": ""},
                                    {"name": "email", "label": "Email", "value": "jane@acme.com"}]},
        "RITM0000002": {"catalog_item": "Contractor access", "requested_for": "bob.lee", "answers": []},
    },
}


@pytest.fixture
def data():
    return copy.deepcopy(DATA)
