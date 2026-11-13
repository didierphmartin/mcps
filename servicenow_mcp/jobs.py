"""The runtime job tools.

They act only on SynergyAI tasks (the configured group + tag prefix): no tool takes a table, a query or an instance,
and every argument that reaches an encoded query is validated against '^'.
"""
from __future__ import annotations

import re
import time
from typing import Callable

from config import Config
from errors import ConnectorError

MAX_TEXT = 4000
STATES = {1: "open", 2: "work_in_progress", 3: "closed_complete", 4: "closed_incomplete", 7: "closed_skipped"}
_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,80}")
_TASK = re.compile(r"[0-9a-f]{32}|SCTASK[0-9]{1,20}")
_GROUP_REST = set(" _.()&/-")
_TAG = {"type": "string", "description": "Only tasks for this playbook tag, e.g. okta-reset."}


def _state_name(state: int) -> str:
    return STATES.get(state, str(state))


class JobsToolset:
    def __init__(self, config: Config, backend, sleep: Callable[[int], None] | None = None,
                 now: Callable[[], float] | None = None):
        self.config = config
        self.backend = backend
        self.sleep = sleep or time.sleep
        self.now = now or time.monotonic

    def tools(self) -> list[dict]:
        task = {"type": "string", "description": "Task sys_id (32 hex) or number (SCTASK…)."}
        text = {"type": "string", "minLength": 1, "maxLength": MAX_TEXT}
        obj = lambda props, required=None: {"type": "object", "additionalProperties": False,  # noqa: E731
                                            **({"required": required} if required else {}), "properties": props}
        return [
            {"name": "poll_jobs",
             "description": "Return the oldest open, unclaimed SynergyAI task with its request's form answers, or job=null.",
             "inputSchema": obj({"tag": _TAG})},
            {"name": "wait_for_jobs",
             "description": ("Wait (up to about two minutes) until an open, unclaimed SynergyAI task exists; answers "
                             "status ready or timeout. Claims nothing."),
             "inputSchema": obj({"tag": _TAG})},
            {"name": "claim_job", "description": "Claim an open SynergyAI task (Work in Progress) before acting on it.",
             "inputSchema": obj({"task": task}, ["task"])},
            {"name": "add_note", "description": "Add a work note to a SynergyAI task.",
             "inputSchema": obj({"task": task, "text": text}, ["task", "text"])},
            {"name": "complete_job", "description": "Close a claimed SynergyAI task as complete, with close notes.",
             "inputSchema": obj({"task": task, "notes": text}, ["task", "notes"])},
            {"name": "hand_back", "description": "Give a SynergyAI task back to a human group, open, with the reason.",
             "inputSchema": obj({"task": task, "group": {"type": "string", "description": "Group name."}, "reason": text},
                                ["task", "group", "reason"])},
            {"name": "describe_item",
             "description": ("Describe the catalog item of an automation (by its key): sys_id, name, stamped version and "
                             "form variables (name, type, mandatory), or item=null. Also reports the instance's "
                             "environment."),
             "inputSchema": obj({"key": {"type": "string", "description": "Automation key, e.g. okta-reset."}}, ["key"])},
        ]

    def call(self, name: str, args: dict) -> dict:
        match name:
            case "poll_jobs":
                return self._poll_jobs(args)
            case "wait_for_jobs":
                return self._wait_for_jobs(args)
            case "claim_job":
                return self._claim_job(args)
            case "add_note":
                return self._add_note(args)
            case "complete_job":
                return self._complete_job(args)
            case "hand_back":
                return self._hand_back(args)
            case "describe_item":
                return self._describe_item(args)
            case _:
                raise ConnectorError("bad_argument", f"unknown tool '{name}'")

    def _describe_item(self, args: dict) -> dict:
        key = args.get("key")
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ConnectorError("bad_argument", "key must match [a-z0-9][a-z0-9._-]*")
        return {"environment": self.config.environment, "item": self.backend.describe_item(key)}

    @staticmethod
    def _tag_arg(args: dict) -> str | None:
        tag = args.get("tag")
        if tag is not None and (not isinstance(tag, str) or not _KEY.fullmatch(tag)):
            raise ConnectorError("bad_argument", "tag must match [a-z0-9][a-z0-9._-]*")
        return tag

    def _wait_for_jobs(self, args: dict) -> dict:
        """Long poll: ready as soon as an open, unclaimed SynergyAI task exists, timeout after the wait window."""
        tag = self._tag_arg(args)
        interval = max(1, self.config.wait_interval)
        deadline = self.now() + self.config.wait_window   # wall time: each check's latency counts
        sleeps = 0
        while True:
            self.backend.refresh()
            if self.backend.find_oldest_open_task(self.config.group, self.config.tag_prefix + (tag or ""),
                                                  tag is not None) is not None:
                return {"status": "ready", "via": "poll"}
            if self.now() + interval > deadline and sleeps > 0:
                return {"status": "timeout", "via": "poll"}
            self.sleep(interval)
            sleeps += 1

    def _poll_jobs(self, args: dict) -> dict:
        tag = self._tag_arg(args)
        task = self.backend.find_oldest_open_task(self.config.group, self.config.tag_prefix + (tag or ""), tag is not None)
        return {"job": None if task is None else self._job(task)}

    def _claim_job(self, args: dict) -> dict:
        task = self._synergy_task(args)
        if not task["active"] or task["state"] != 1:
            raise ConnectorError("not_claimable", f"task {task['number']} is {_state_name(task['state'])}, not open")
        self.backend.update_task(task["sys_id"], {"state": 2, "work_notes": "Claimed by SynergyAI."})
        task["state"] = 2
        return self._job(task)

    def _add_note(self, args: dict) -> dict:
        task = self._active(self._synergy_task(args))
        self.backend.update_task(task["sys_id"], {"work_notes": self._text(args, "text")})
        return {"task": task["sys_id"], "number": task["number"], "noted": True}

    def _complete_job(self, args: dict) -> dict:
        task = self._synergy_task(args)
        notes = self._text(args, "notes")
        if task["state"] != 2:
            raise ConnectorError("not_claimed", f"task {task['number']} is {_state_name(task['state'])}; claim it first")
        self.backend.update_task(task["sys_id"], {"state": 3, "close_notes": notes, "work_notes": "Completed by SynergyAI."})
        return {"task": task["sys_id"], "number": task["number"], "state": "closed_complete"}

    def _hand_back(self, args: dict) -> dict:
        task = self._active(self._synergy_task(args))
        group = args.get("group")
        # A group name only: no encoded-query or javascript: syntax reaches ServiceNow.
        if (not isinstance(group, str) or not 1 <= len(group) <= 100 or not group[0].isalnum()
                or not all(c.isalnum() or c in _GROUP_REST for c in group[1:])):
            raise ConnectorError("bad_argument", "group must be a group name (letters, digits, space . _ ( ) & / -)")
        if group.lower() == self.config.group.lower():
            raise ConnectorError("bad_argument", "hand_back goes to a human group, not the SynergyAI group")
        reason = self._text(args, "reason")
        group_id = self.backend.find_group_sys_id(group)
        if group_id is None:
            raise ConnectorError("group_not_found", f"no group named '{group}'")
        self.backend.update_task(task["sys_id"], {"assignment_group": group_id, "state": 1,
                                                  "work_notes": f"Handed back by SynergyAI: {reason}"})
        return {"task": task["sys_id"], "number": task["number"], "state": "open", "group": group}

    def _synergy_task(self, args: dict) -> dict:
        """The task named by args['task'], which must be a SynergyAI task (configured group + tag prefix)."""
        ref = args.get("task")
        if not isinstance(ref, str) or not _TASK.fullmatch(ref):
            raise ConnectorError("bad_argument", "task must be a 32-hex sys_id or an SCTASK number")
        task = self.backend.get_task(ref)
        if (task is None or task["assignment_group"] != self.config.group
                or not task["correlation_display"].startswith(self.config.tag_prefix)):
            raise ConnectorError("task_not_found", f"no SynergyAI task {ref}")
        return task

    @staticmethod
    def _active(task: dict) -> dict:
        """The task, if still open or in progress: closed work is never reopened or annotated."""
        if not task["active"] or task["state"] not in (1, 2):
            raise ConnectorError("not_claimable", f"task {task['number']} is {_state_name(task['state'])}")
        return task

    def _job(self, task: dict) -> dict:
        answers = {}
        if task["request_item"] != "":
            for a in self.backend.get_answers(task["request_item"]):
                if (a.get("name") or "") != "":
                    answers[a["name"]] = {"label": a["label"], "value": a["value"]}
        tag = task["correlation_display"][len(self.config.tag_prefix):]
        m = re.fullmatch(re.escape(tag) + r"@([0-9]+)", task.get("correlation_id") or "")
        return {
            "task": task["sys_id"],
            "number": task["number"],
            "tag": tag,
            "version": int(m.group(1)) if m else None,
            "catalog_item_id": task.get("catalog_item_id") or "",
            "state": _state_name(task["state"]),
            "short_description": task["short_description"],
            "request_item": task["request_item_number"],
            "catalog_item": task["catalog_item"],
            "requested_for": task["requested_for"],
            "answers": answers,
        }

    @staticmethod
    def _text(args: dict, key: str) -> str:
        v = args.get(key)
        if not isinstance(v, str) or v.strip() == "" or len(v) > MAX_TEXT:
            raise ConnectorError("bad_argument", f"{key} must be 1-{MAX_TEXT} characters")
        return v
