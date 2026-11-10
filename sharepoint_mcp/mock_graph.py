"""An httpx transport that plays Microsoft identity + Graph for tests and SHAREPOINT_MOCK_GRAPH=1.

Implements only what this server calls. Every request is logged in .requests so tests can prove
what was (and was not) fetched. Sites, document libraries and folder driveItems are in memory;
names are case-insensitive, as in SharePoint.
"""
from __future__ import annotations

import base64
import itertools
import json
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx


class MockGraph:
    UPLOAD_HOST = "upload.mock"

    def __init__(self):
        self.requests: list[tuple[str, str]] = []
        self.headers: list[dict[str, str]] = []   # each request's headers, in the order of .requests
        self._tokens = itertools.count(1)
        self.access_tokens: set[str] = set()
        self.refresh_tokens: set[str] = set()
        self.device_state = "pending"
        self.throttle_next = 0
        self.forbid = False                       # a connection consented without Sites.ReadWrite.All: 403
        self.account, self.tenant = "me@contoso.com", "tid-1"
        self._request: httpx.Request | None = None
        self.sites: dict[str, str] = {}           # "host:/sites/path" (lower case) -> site id
        self.drives: dict[str, list[dict]] = {}   # site id -> [{"id", "name", "webUrl"}]
        self.items: dict[str, dict[str, dict]] = {}   # drive id -> {lower-case path: driveItem}
        self.sessions: dict[str, dict] = {}       # upload session id -> {"drive", "folder", "name", "conflict", "data"}
        self.chunk_fault: tuple[int, ...] | None = None   # (1-based chunk request, HTTP status[, times]) to answer instead
        self._chunks = 0
        self.session_conflicts: list[str] = []    # conflictBehavior each upload session was created with

    # test controls -------------------------------------------------------------
    def revoke_refresh(self) -> None:
        self.refresh_tokens.clear()

    def expire_access_tokens(self) -> None:
        self.access_tokens.clear()

    def add_library(self, site: str, name: str) -> str:
        """Make a document library in a site (created on first use); returns the drive id."""
        site_id = self.sites.setdefault(site.lower(), f"site-{len(self.sites) + 1}")
        drive_id = f"drive-{sum(len(d) for d in self.drives.values()) + 1}"
        self.drives.setdefault(site_id, []).append({"id": drive_id, "name": name, "webUrl": f"https://mock/{name}"})
        self.items[drive_id] = {}
        return drive_id

    def folder_paths(self, drive_id: str) -> list[str]:
        """The folders in a library, as created (original case), sorted."""
        return sorted(i["_path"] for i in self.items[drive_id].values() if "folder" in i)

    def files(self, drive_id: str) -> dict[str, bytes]:
        """The files in a library: path (original case) -> content."""
        return {i["_path"]: i["_content"] for i in self.items[drive_id].values() if "file" in i}

    # transport -------------------------------------------------------------------
    def _tokens_response(self) -> httpx.Response:
        at, rt = f"AT{next(self._tokens)}", f"RT{next(self._tokens)}"
        self.access_tokens.add(at)
        self.refresh_tokens.add(rt)
        claims = base64.urlsafe_b64encode(json.dumps({"tid": self.tenant}).encode()).decode().rstrip("=")
        return httpx.Response(200, json={"access_token": at, "refresh_token": rt, "expires_in": 3600,
                                         "id_token": f"h.{claims}.s"})

    @staticmethod
    def _oauth_error(code: str, desc: str = "") -> httpx.Response:
        return httpx.Response(400, json={"error": code, "error_description": desc})

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        self.requests.append((request.method, url.path + (f"?{url.query}" if url.query else "")))
        self.headers.append(dict(request.headers))
        self._request = request                   # what _graph answers (its method and body)
        if url.netloc == self.UPLOAD_HOST:        # a pre-authenticated upload URL: no bearer token, as in Graph
            return self._upload_chunk(url.path.rsplit("/", 1)[-1], request)
        if url.path.endswith("/oauth2/v2.0/devicecode"):
            return httpx.Response(200, json={"device_code": "dc-1", "user_code": "K7PQ-M2XD",
                                             "verification_uri": "https://microsoft.com/devicelogin",
                                             "expires_in": 900, "interval": 5})
        if url.path.endswith("/oauth2/v2.0/token"):
            return self._token(parse_qs(request.content.decode()))
        if self.throttle_next:
            self.throttle_next -= 1
            return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {"code": "TooManyRequests"}})
        if request.headers.get("Authorization", "").removeprefix("Bearer ") not in self.access_tokens:
            return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken"}})
        if self.forbid:
            return httpx.Response(403, json={"error": {"code": "accessDenied", "message": "Access denied"}})
        return self._graph(url.path.split("/v1.0", 1)[-1], parse_qs(url.query))

    def _token(self, form: dict) -> httpx.Response:
        match form.get("grant_type", [""])[0]:
            case "urn:ietf:params:oauth:grant-type:device_code":
                match self.device_state:
                    case "pending":
                        return self._oauth_error("authorization_pending")
                    case "blocked":
                        return self._oauth_error("invalid_grant", "AADSTS53003: Access has been blocked by Conditional Access policies.")
                    case "declined":
                        return self._oauth_error("authorization_declined")
                    case _:
                        return self._tokens_response()
            case "refresh_token":
                if form.get("refresh_token", [""])[0] not in self.refresh_tokens:
                    return self._oauth_error("invalid_grant", "AADSTS70008: The refresh token has expired.")
                return self._tokens_response()
            case "authorization_code":
                return self._tokens_response()
            case _:
                return self._oauth_error("unsupported_grant_type")

    def _graph(self, path: str, q: dict) -> httpx.Response:
        path = unquote(path)
        if m := re.fullmatch(r"/sites/([^/]+:/.+)", path):
            site_id = self.sites.get(m.group(1).lower())
            return self._found({"id": site_id, "name": m.group(1)} if site_id else None)
        if m := re.fullmatch(r"/sites/([^/:]+)/drives", path):
            return httpx.Response(200, json={"value": self.drives.get(m.group(1), [])})
        if m := re.fullmatch(r"/drives/([^/]+)/root:/(.+):/content", path):
            return self._put_content(m.group(1), m.group(2), q, self._request.content)
        if m := re.fullmatch(r"/drives/([^/]+)/root:/(.+):/createUploadSession", path):
            return self._create_session(m.group(1), m.group(2), json.loads(self._request.content))
        if m := re.fullmatch(r"/drives/([^/]+)/(?:root:/(.+?)(:/children)?|root/(children))", path):
            drive_id, rel, colon_children, root_children = m.groups()
            if drive_id not in self.items:
                return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
            if self._request.method == "POST":
                return self._create_folder(drive_id, (rel or "").strip("/") if colon_children else "", self._request)
            return self._found(self.items[drive_id].get((rel or "").strip("/").lower()))
        match path.strip("/").split("/"):
            case ["me"]:
                return httpx.Response(200, json={"mail": self.account, "userPrincipalName": self.account})
        return httpx.Response(404, json={"error": {"code": "NotImplementedInMock", "path": path}})

    @staticmethod
    def _found(item: dict | None) -> httpx.Response:
        if item is None:
            return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
        return httpx.Response(200, json={k: v for k, v in item.items() if not k.startswith("_")})

    def _create_folder(self, drive_id: str, parent: str, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        items = self.items[drive_id]
        if parent and parent.lower() not in items:
            return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
        name = self._free_name(items, parent, body["name"], body.get("@microsoft.graph.conflictBehavior", "rename"))
        if name is None:
            return httpx.Response(409, json={"error": {"code": "nameAlreadyExists"}})
        item = self._store(items, parent, name, {"folder": {}})
        return httpx.Response(201, json=self._public(item))

    # files ---------------------------------------------------------------------------
    @staticmethod
    def _public(item: dict) -> dict:
        return {k: v for k, v in item.items() if not k.startswith("_")}

    @staticmethod
    def _free_name(items: dict, parent: str, name: str, conflict: str) -> str | None:
        """The name an item gets under conflictBehavior: fail -> None on a clash; rename -> 'name 1.ext'; else as is."""
        def taken(n): return (f"{parent}/{n}" if parent else n).lower() in items
        if not taken(name) or conflict == "replace":
            return name
        if conflict == "fail":
            return None
        stem, dot, ext = name.rpartition(".") if "." in name.strip(".") else (name, "", "")
        return next(c for n in itertools.count(1) if not taken(c := f"{stem} {n}{dot}{ext}"))

    def _store(self, items: dict, parent: str, name: str, facets: dict, content: bytes | None = None) -> dict:
        path = f"{parent}/{name}" if parent else name
        old = items.get(path.lower())
        item = {"id": old["id"] if old else f"item-{sum(len(i) for i in self.items.values()) + 1}", "name": name,
                "size": len(content or b""), "webUrl": f"https://mock/{path}", **facets, "_path": path}
        if content is not None:
            item["_content"] = content
        items[path.lower()] = item
        return item

    def _put_file(self, drive_id: str, rel: str, conflict: str, content: bytes) -> httpx.Response:
        items = self.items[drive_id]
        parent, _, name = rel.rpartition("/")
        for i in range(parent.count("/") + 1 if parent else 0):        # Graph creates the missing folders of a path
            sub = "/".join(parent.split("/")[:i + 1])
            if sub.lower() not in items:
                self._store(items, "/".join(sub.split("/")[:-1]), sub.split("/")[-1], {"folder": {}})
        replaced = name and f"{parent}/{name}".strip("/").lower() in items
        final = self._free_name(items, parent, name, conflict)
        if final is None:
            return httpx.Response(409, json={"error": {"code": "nameAlreadyExists"}})
        item = self._store(items, parent, final, {"file": {}}, content)
        return httpx.Response(200 if replaced and conflict == "replace" else 201, json=self._public(item))

    def _put_content(self, drive_id: str, rel: str, q: dict, content: bytes) -> httpx.Response:
        if drive_id not in self.items:
            return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
        return self._put_file(drive_id, rel, q.get("@microsoft.graph.conflictBehavior", ["rename"])[0], content)

    def _create_session(self, drive_id: str, rel: str, body: dict) -> httpx.Response:
        if drive_id not in self.items:
            return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
        conflict = body.get("item", {}).get("@microsoft.graph.conflictBehavior", "rename")
        self.session_conflicts.append(conflict)
        sid = f"session-{len(self.sessions) + 1}"
        self.sessions[sid] = {"drive": drive_id, "rel": rel, "conflict": conflict, "data": b""}
        return httpx.Response(200, json={"uploadUrl": f"https://{self.UPLOAD_HOST}/upload/{sid}",
                                         "expirationDateTime": "2099-01-01T00:00:00Z"})

    def _upload_chunk(self, sid: str, request: httpx.Request) -> httpx.Response:
        s = self.sessions.get(sid)
        self._chunks += 1
        if self.chunk_fault and self.chunk_fault[0] <= self._chunks < self.chunk_fault[0] + (self.chunk_fault + (1,))[2]:
            return httpx.Response(self.chunk_fault[1], headers={"Retry-After": "0"}, json={"error": {"code": "fault"}})
        m = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", request.headers.get("Content-Range", ""))
        if s is None or m is None or int(m[1]) != len(s["data"]) or int(request.headers.get("Content-Length", -1)) != len(request.content):
            return httpx.Response(416, json={"error": {"code": "invalidRange"}})
        s["data"] += request.content
        if len(s["data"]) < int(m[3]):
            return httpx.Response(202, json={"expirationDateTime": "2099-01-01T00:00:00Z",
                                             "nextExpectedRanges": [f"{len(s['data'])}-"]})
        return self._put_file(s["drive"], s["rel"], s["conflict"], s["data"])
