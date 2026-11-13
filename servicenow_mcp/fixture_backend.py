"""Backend over fixture data (SN_INSTANCE=mock).

Updates live in memory; with_state() also saves them to a state file after every change and reads it back on the next
request, so the mock remembers claims, notes and completions until the file is reset (reset_mock.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from errors import ConnectorError


class FixtureBackend:
    def __init__(self, data: dict):
        self.data = data
        self.groups = {hashlib.md5(name.encode()).hexdigest(): name for name in data.get("groups") or []}
        self.state_path: Path | None = None
        self.fixture_path: Path | None = None
        self._load(data)

    def _load(self, data: dict) -> None:
        self.notes: dict[str, list[str]] = {k: list(v) for k, v in (data.get("notes") or {}).items()}
        self.tasks: dict[str, dict] = {t["sys_id"]: dict(t) for t in data.get("tasks") or []}

    @classmethod
    def from_file(cls, path: Path) -> "FixtureBackend":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if not isinstance(data, dict):
            raise ConnectorError("bad_config", "mock fixture is not valid JSON")
        return cls(data)

    @classmethod
    def with_state(cls, fixture_path: Path, state_path: Path) -> "FixtureBackend":
        """The fixture, or the state saved by an earlier request when there is one."""
        state_path = Path(state_path)
        b = cls.from_file(state_path if state_path.is_file() else fixture_path)
        b.state_path = state_path
        b.fixture_path = Path(fixture_path)
        return b

    @staticmethod
    def reset_state(state_path: Path) -> None:
        """Forget every change: the next request starts from the fixture again."""
        Path(state_path).unlink(missing_ok=True)

    def refresh(self) -> None:
        if self.state_path is None:
            return
        path = self.state_path if self.state_path.is_file() else self.fixture_path
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            self._load(data)

    def _save(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(mode=0o775, parents=True, exist_ok=True)
        state = {"groups": list(self.groups.values()), "tasks": list(self.tasks.values()),
                 "request_items": self.data.get("request_items") or {}, "items": self.data.get("items") or {},
                 "notes": self.notes}
        tmp = Path(f"{self.state_path}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, indent=4, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.state_path)   # atomic: a concurrent request reads the old or the new state

    def describe_item(self, key: str) -> dict | None:
        item = (self.data.get("items") or {}).get(key)
        if not isinstance(item, dict):
            return None
        version = None
        variables = []
        for v in item.get("variables") or []:
            if v["name"] == "synergyai_automation":
                m = re.fullmatch(re.escape(key) + r"@([0-9]+)", str(v.get("default_value") or ""))
                version = int(m.group(1)) if m else None
                continue
            variables.append({"name": str(v["name"]), "type": str(v.get("type") or "6"),
                              "mandatory": bool(v.get("mandatory") or False)})
        return {"sys_id": str(item.get("sys_id") or ""), "name": str(item.get("name") or ""), "version": version,
                "variables": variables}

    def find_oldest_open_task(self, group: str, tag: str, exact: bool = False) -> dict | None:
        open_ = [t for t in self.tasks.values()
                 if t["active"] and int(t["state"]) == 1 and t["assignment_group"] == group
                 and (t["correlation_display"] == tag if exact else t["correlation_display"].startswith(tag))]
        open_.sort(key=lambda t: t["created"])
        return self._normalize(open_[0]) if open_ else None

    def get_task(self, ref: str) -> dict | None:
        for t in self.tasks.values():
            if t["sys_id"] == ref or t["number"] == ref:
                return self._normalize(t)
        return None

    def get_answers(self, request_item: str) -> list[dict]:
        return ((self.data.get("request_items") or {}).get(request_item) or {}).get("answers") or []

    def update_task(self, sys_id: str, fields: dict) -> None:
        t = self.tasks.get(sys_id)
        if t is None:
            raise ConnectorError("task_not_found", f"no task {sys_id}")
        if "state" in fields:
            t["state"] = int(fields["state"])
            t["active"] = t["state"] in (1, 2)
        if "assignment_group" in fields:
            t["assignment_group"] = self.groups.get(fields["assignment_group"], t["assignment_group"])
        if "close_notes" in fields:
            t["close_notes"] = fields["close_notes"]
        if "work_notes" in fields:
            self.notes.setdefault(sys_id, []).append(fields["work_notes"])
        self._save()

    def find_group_sys_id(self, name: str) -> str | None:
        return next((gid for gid, n in self.groups.items() if n == name), None)

    def task_notes(self, sys_id: str) -> list[str]:
        """Work notes added to a task, oldest first."""
        return list(self.notes.get(sys_id, []))

    def _normalize(self, t: dict) -> dict:
        ri = (self.data.get("request_items") or {}).get(t["request_item"]) or {}
        return {
            "sys_id": t["sys_id"],
            "number": t["number"],
            "state": int(t["state"]),
            "active": bool(t["active"]),
            "assignment_group": t["assignment_group"],
            "correlation_display": t["correlation_display"],
            "correlation_id": str(t.get("correlation_id") or ""),
            "short_description": t["short_description"],
            "request_item": t["request_item"],
            "request_item_number": t["request_item"],
            "catalog_item": ri.get("catalog_item", ""),
            "catalog_item_id": ri.get("catalog_item_id", ""),
            "requested_for": ri.get("requested_for", ""),
        }
