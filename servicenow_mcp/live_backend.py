"""Backend over the ServiceNow Table API, with an OAuth client-credentials token."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode

import httpx

from config import Config
from errors import ConnectorError

# (method, url, headers, body) -> {"status": int, "body": str}
Transport = Callable[[str, str, dict, "str | None"], dict]

TASK_FIELDS = ("sys_id,number,state,active,short_description,correlation_display,correlation_id,assignment_group.name,"
               "request_item,request_item.number,request_item.cat_item,request_item.cat_item.name,"
               "request_item.requested_for.user_name")
_SYS_ID = re.compile(r"[0-9a-f]{32}")


def http_transport(timeout: int) -> Transport:
    """HTTP for the backend and the token: no redirects followed; a connection failure is instance_unavailable."""
    def send(method: str, url: str, headers: dict, body: str | None) -> dict:
        try:
            r = httpx.request(method, url, headers=headers, content=body, follow_redirects=False,
                              timeout=httpx.Timeout(timeout, connect=min(10, timeout)))
        except httpx.HTTPError as e:
            raise ConnectorError("instance_unavailable", f"cannot reach ServiceNow: {e}") from None
        return {"status": r.status_code, "body": r.text}
    return send


class TokenProvider:
    """OAuth client-credentials token, kept in memory and in a 0600 cache file until 60 s before it expires."""

    def __init__(self, config: Config, transport: Transport, cache_dir: Path, now: Callable[[], int] | None = None):
        self.config = config
        self.transport = transport
        self.cache_file = Path(cache_dir) / "token.json"
        self.now = now or (lambda: int(time.time()))
        self._token: dict | None = None

    def token(self) -> str:
        now = self.now()
        if self._token is not None and self._token["expires_at"] - 60 > now:
            return self._token["access_token"]
        cached = self._read_cache()
        if cached is not None and cached["expires_at"] - 60 > now:
            self._token = cached
            return cached["access_token"]
        r = self.transport("POST", self.config.instance + "/oauth_token.do",
                           {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                           urlencode({"grant_type": "client_credentials", "client_id": self.config.client_id,
                                      "client_secret": self.config.client_secret}))
        try:
            data = json.loads(r["body"])
        except ValueError:
            data = None
        status = r["status"]
        if status >= 500 or 300 <= status < 400 or (status == 200 and not isinstance(data, dict)):
            raise ConnectorError("instance_unavailable",
                                 f"token endpoint did not answer normally (HTTP {status}; instance asleep?)")
        if status != 200 or not isinstance(data.get("access_token"), str):
            raise ConnectorError("auth_failed",
                                 f"token request refused (HTTP {status}): check SN_CLIENT_ID / SN_CLIENT_SECRET")
        try:
            expires_in = int(data.get("expires_in") or 0)
        except (TypeError, ValueError):
            expires_in = 0
        self._token = {"access_token": data["access_token"], "expires_at": now + expires_in}
        self._write_cache(self._token)
        return self._token["access_token"]

    def invalidate(self) -> None:
        self._token = None
        self.cache_file.unlink(missing_ok=True)

    def _read_cache(self) -> dict | None:
        try:
            d = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        ok = isinstance(d, dict) and isinstance(d.get("access_token"), str) and type(d.get("expires_at")) is int
        return d if ok else None

    def _write_cache(self, token: dict) -> None:
        self.cache_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.cache_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(token))
        os.chmod(self.cache_file, 0o600)


class LiveBackend:
    def __init__(self, config: Config, tokens: TokenProvider, transport: Transport):
        self.config = config
        self.tokens = tokens
        self.transport = transport

    def find_oldest_open_task(self, group: str, tag: str, exact: bool = False) -> dict | None:
        match = f"correlation_display={tag}" if exact else f"correlation_displaySTARTSWITH{tag}"
        rows = self._send("GET", "/api/now/table/sc_task", {
            "sysparm_query": f"active=true^assignment_group.name={group}^{match}^state=1^ORDERBYsys_created_on",
            "sysparm_fields": TASK_FIELDS, "sysparm_limit": "1", "sysparm_exclude_reference_link": "true",
        }, None, "poll tasks")
        return _task(rows[0]) if rows else None

    def get_task(self, ref: str) -> dict | None:
        fields = {"sysparm_fields": TASK_FIELDS, "sysparm_exclude_reference_link": "true"}
        if _SYS_ID.fullmatch(ref):
            row = self._send("GET", f"/api/now/table/sc_task/{ref}", fields, None, "read task", allow_404=True)
            return None if row is None else _task(row)
        rows = self._send("GET", "/api/now/table/sc_task", {"sysparm_query": f"number={ref}", "sysparm_limit": "1", **fields},
                          None, "read task")
        return _task(rows[0]) if rows else None

    def get_answers(self, request_item: str) -> list[dict]:
        rows = self._send("GET", "/api/now/table/sc_item_option_mtom", {
            "sysparm_query": f"request_item={request_item}^ORDERBYsc_item_option.order",
            "sysparm_fields": ("sc_item_option.item_option_new.name,sc_item_option.item_option_new.question_text,"
                               "sc_item_option.value"),
        }, None, "read answers") or []
        return [{"name": str(r.get("sc_item_option.item_option_new.name") or ""),
                 "label": str(r.get("sc_item_option.item_option_new.question_text") or ""),
                 "value": str(r.get("sc_item_option.value") or "")} for r in rows]

    def update_task(self, sys_id: str, fields: dict) -> None:
        self._send("PATCH", f"/api/now/table/sc_task/{sys_id}", {"sysparm_fields": "sys_id"},
                   json.dumps({k: str(v) for k, v in fields.items()}), "update task")

    def find_group_sys_id(self, name: str) -> str | None:
        rows = self._send("GET", "/api/now/table/sys_user_group",
                          {"sysparm_query": f"name={name}^active=true", "sysparm_fields": "sys_id", "sysparm_limit": "1"},
                          None, "find group")
        return rows[0].get("sys_id") if rows else None

    def describe_item(self, key: str) -> dict | None:
        stamp = self._send("GET", "/api/now/table/item_option_new", {
            "sysparm_query": f"name=synergyai_automation^default_valueSTARTSWITH{key}@",
            "sysparm_fields": "cat_item,default_value", "sysparm_limit": "1", "sysparm_exclude_reference_link": "true",
        }, None, "find catalog item")
        item_id = str((stamp[0] if stamp else {}).get("cat_item") or "")
        if not _SYS_ID.fullmatch(item_id):
            return None
        m = re.fullmatch(re.escape(key) + r"@([0-9]+)", str(stamp[0].get("default_value") or ""))
        rows = self._send("GET", "/api/now/table/item_option_new", {
            "sysparm_query": f"cat_item={item_id}^name!=synergyai_automation^ORDERBYorder",
            "sysparm_fields": "name,type,mandatory", "sysparm_exclude_reference_link": "true",
        }, None, "read catalog variables") or []
        item = self._send("GET", f"/api/now/table/sc_cat_item/{item_id}",
                          {"sysparm_fields": "name", "sysparm_exclude_reference_link": "true"}, None, "read catalog item",
                          allow_404=True) or {}
        return {"sys_id": item_id, "name": str(item.get("name") or ""), "version": int(m.group(1)) if m else None,
                "variables": [{"name": str(r.get("name") or ""), "type": str(r.get("type") or ""),
                               "mandatory": r.get("mandatory") == "true"} for r in rows if isinstance(r, dict)]}

    def refresh(self) -> None:
        """Caches nothing."""

    def _send(self, method: str, path: str, query: dict, body: str | None, op: str, allow_404: bool = False):
        """One API call with the bearer token; a 401 refreshes the token and retries once. Returns "result"."""
        url = self.config.instance + path + "?" + urlencode(query, quote_via=quote, safe="")
        for attempt in range(2):
            headers = {"Authorization": "Bearer " + self.tokens.token(), "Accept": "application/json"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            r = self.transport(method, url, headers, body)
            if r["status"] != 401 or attempt > 0:
                break
            self.tokens.invalidate()
        status = r["status"]
        if status == 401:
            raise ConnectorError("auth_failed", f"ServiceNow refused the token ({op})")
        if status == 403:
            raise ConnectorError("forbidden", f"not allowed to {op}")
        if status == 404 and allow_404:
            return None
        try:
            data = json.loads(r["body"])
        except ValueError:
            data = None
        if status >= 300 or not isinstance(data, dict):
            raise ConnectorError("instance_unavailable", f"ServiceNow did not answer normally ({op}, HTTP {status})")
        result = data.get("result")
        return result if isinstance(result, (dict, list)) else None


def _task(r: dict) -> dict:
    try:
        state = int(r.get("state") or 0)
    except (TypeError, ValueError):
        state = 0
    return {
        "sys_id": str(r.get("sys_id") or ""),
        "number": str(r.get("number") or ""),
        "state": state,
        "active": r.get("active") == "true",
        "assignment_group": str(r.get("assignment_group.name") or ""),
        "correlation_display": str(r.get("correlation_display") or ""),
        "correlation_id": str(r.get("correlation_id") or ""),
        "short_description": str(r.get("short_description") or ""),
        "request_item": str(r.get("request_item") or ""),
        "request_item_number": str(r.get("request_item.number") or ""),
        "catalog_item": str(r.get("request_item.cat_item.name") or ""),
        "catalog_item_id": str(r.get("request_item.cat_item") or ""),
        "requested_for": str(r.get("request_item.requested_for.user_name") or ""),
    }
