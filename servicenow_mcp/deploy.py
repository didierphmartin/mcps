"""Installs a generated Fluent app on a dev or test instance with the ServiceNow SDK.

Refused unless SN_ENVIRONMENT is dev or test with install credentials, and the caller presents SN_DEPLOY_TOKEN as a
Bearer token. Files are checked against an allowlist and written under <root>/<scope>/; the SDK commands run as argv
lists (no shell).
"""
from __future__ import annotations

import hmac
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

from config import Config
from errors import ConnectorError

_SCOPE = re.compile(r"x_[a-z0-9]{1,10}_[a-z0-9]{1,16}")
_FLUENT = re.compile(r"src/fluent/(?:[A-Za-z0-9_-][A-Za-z0-9._-]*/)*[A-Za-z0-9_-][A-Za-z0-9._-]*\.ts")
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,80}")
_EXACT = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
MAX_BYTES = 2 * 1024 * 1024
KEYS = "src/fluent/generated/keys.ts"
STEP_TIMEOUT = 300
TAIL = 1500
ALLOWED_DEPS = ("@servicenow/sdk", "@servicenow/glide", "typescript")

# (argv, cwd, extra env, timeout, stdin) -> {"code": int, "out": str}  (stdout and stderr together)
Runner = Callable[[list, str, dict, int, "str | None"], dict]


def run_command(cmd: list, cwd: str, env: dict, timeout: int, stdin: str | None = None) -> dict:
    """Runs one command (argv list, never a shell string) in `cwd`, with `env` on top of this process's environment."""
    try:
        p = subprocess.run(cmd, cwd=cwd, env={**os.environ, **env}, input=stdin, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out = e.output.decode(errors="replace") if isinstance(e.output, bytes) else (e.output or "")
        return {"code": 124, "out": out + f"\ntimed out after {timeout}s\n"}
    except OSError:
        return {"code": 1, "out": f"cannot start {cmd[0]}"}
    return {"code": p.returncode, "out": p.stdout or ""}


class DeployToolset:
    def __init__(self, config: Config, runner: Runner, root: Path, authorization: str | None = None):
        self.config = config
        self.runner = runner
        self.root = Path(root)
        self.authorization = authorization

    def tools(self) -> list[dict]:
        return [{"name": "install_app",
                 "description": "Build and install a generated Fluent app on this dev/test instance. Refused on prod.",
                 "inputSchema": {"type": "object", "additionalProperties": False, "required": ["scope", "files"],
                                 "properties": {
                                     "scope": {"type": "string", "description": "App scope, x_<company>_<name>."},
                                     "files": {"type": "object",
                                               "description": ("Relative path => text. Allowed: package.json, "
                                                               "now.config.json, src/fluent/**.ts."),
                                               "additionalProperties": {"type": "string"}}}}}]

    def call(self, name: str, args: dict) -> dict:
        self._assert_token()
        if name != "install_app":
            raise ConnectorError("bad_argument", f"unknown tool '{name}'")
        return self._install(args)

    def _assert_token(self) -> None:
        """The caller must present Authorization: Bearer <SN_DEPLOY_TOKEN>."""
        token = self.config.deploy_token
        m = re.fullmatch(r"Bearer (.+)", self.authorization) if isinstance(self.authorization, str) else None
        given = m.group(1) if m else ""
        if token == "" or given == "" or not hmac.compare_digest(token.encode(), given.encode()):
            raise ConnectorError("not_allowed", "deploy needs SN_DEPLOY_TOKEN as a Bearer token")

    def _install(self, args: dict) -> dict:
        c = self.config
        if c.environment not in ("dev", "test") or c.install_user == "" or c.install_password == "":
            raise ConnectorError("not_allowed", "this instance cannot install apps (SN_ENVIRONMENT must be dev or test, "
                                                "with SN_INSTALL_USER and SN_INSTALL_PASSWORD)")
        scope, files = args.get("scope"), args.get("files")
        if not isinstance(scope, str) or not _SCOPE.fullmatch(scope):
            raise ConnectorError("bad_argument", "scope must match ^x_[a-z0-9]{1,10}_[a-z0-9]{1,16}$")
        if not isinstance(files, dict) or not files:
            raise ConnectorError("bad_argument", "files must be a non-empty object of path => text")
        total = 0
        for path, text in files.items():
            path = str(path)
            if not _allowed_path(path):
                raise ConnectorError("bad_argument", "path not allowed: " + path.encode("unicode_escape").decode()[:80])
            if not isinstance(text, str):
                raise ConnectorError("bad_argument", f"content of {path} must be text")
            if path == "package.json":
                _assert_package_json(text)
            total += len(text.encode())
        if total > MAX_BYTES:
            raise ConnectorError("bad_argument", "files exceed 2 MB in total")

        app_dir = self.root / scope
        self._write_files(app_dir, files)
        # The SDK login and the npm cache stay inside the server folder, not in the user's home.
        home, cache = self.root / ".home", self.root / ".npm-cache"
        for d in (home, cache):
            try:
                if d.is_symlink():
                    raise OSError
                d.mkdir(mode=0o700, parents=True, exist_ok=True)
            except OSError:
                raise ConnectorError("install_failed", "cannot prepare the deploy home folder") from None
        env = {"HOME": str(home), "npm_config_cache": str(cache)}
        npx = c.npx
        npm = os.path.join(os.path.dirname(npx), "npm") if "/" in npx else "npm"
        if "/" in npx:
            # npm and npx run "#!/usr/bin/env node": node lives next to them, often not on the server's PATH
            env["PATH"] = os.path.dirname(npx) + os.pathsep + os.environ.get("PATH", "")
        steps = []
        if not (app_dir / "node_modules").is_dir():
            steps.append(([npm, "install", "--ignore-scripts"], {}))
        steps.append(([npx, "--no-install", "now-sdk", "build"], {}))
        # No stored login: the SDK's CI mode reads the credentials from the install step's environment (never argv);
        # no other step gets them.
        steps.append(([npx, "--no-install", "now-sdk", "install"], {
            "SN_SDK_NODE_ENV": "SN_SDK_CI_INSTALL", "SN_SDK_AUTH_TYPE": "basic", "SN_SDK_INSTANCE_URL": c.instance,
            "SN_SDK_USER": c.install_user, "SN_SDK_USER_PWD": c.install_password}))
        tail = ""
        for cmd, step_env in steps:
            r = self.runner(cmd, str(app_dir), {**env, **step_env}, STEP_TIMEOUT, None)
            tail = self._tail(r["out"])
            if r["code"] != 0:
                raise ConnectorError("install_failed", f"exit {r['code']} from {' '.join(cmd[:4])}: {tail}")
        return {"installed": True, "scope": scope, "log_tail": tail}

    def _write_files(self, app_dir: Path, files: dict) -> None:
        # Check every target first so a refusal leaves nothing half-written.
        plan = {}
        for path, text in files.items():
            target = app_dir / str(path)
            if str(path) == KEYS and target.exists():
                continue
            plan[target] = text
        for target in plan:
            self._assert_no_symlink(app_dir, target)
        for target, text in plan.items():
            try:
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            except OSError:
                raise ConnectorError("install_failed", "cannot create the app folder") from None
            self._assert_no_symlink(app_dir, target)
            try:
                target.write_text(text, encoding="utf-8")
            except OSError:
                raise ConnectorError("install_failed", "cannot write the app files") from None

    def _assert_no_symlink(self, app_dir: Path, target: Path) -> None:
        """Neither the root, the app folder, any folder below it nor the file itself may be a symbolic link."""
        paths = [self.root, app_dir]
        cur = app_dir
        for part in target.relative_to(app_dir).parts:
            cur = cur / part
            paths.append(cur)
        if any(p.is_symlink() for p in paths):
            raise ConnectorError("bad_argument", "the app folder contains a symbolic link")

    def _tail(self, out: str) -> str:
        if self.config.install_password:
            out = out.replace(self.config.install_password, "***")
        return out[-TAIL:] if len(out) > TAIL else out


def _allowed_path(p: str) -> bool:
    if p in ("package.json", "now.config.json"):
        return True
    return _FLUENT.fullmatch(p) is not None and ".." not in p


def _assert_package_json(text: str) -> None:
    """Only what the generator writes: fixed scripts, three exact-version dependencies, nothing that runs code."""
    try:
        j = json.loads(text)
    except ValueError:
        j = None
    if not isinstance(j, dict):
        raise ConnectorError("bad_argument", "package.json must be a JSON object")
    extra = [k for k in j if k not in ("name", "version", "private", "scripts", "devDependencies", "dependencies")]
    if extra:
        raise ConnectorError("bad_argument", "package.json: key not allowed: " + ",".join(extra)[:60])
    if "scripts" in j and j["scripts"] != {"build": "now-sdk build", "deploy": "now-sdk install"}:
        raise ConnectorError("bad_argument", "package.json: scripts must be exactly build=now-sdk build, deploy=now-sdk install")
    for k in ("name", "version"):
        if k in j and (not isinstance(j[k], str) or not _NAME.fullmatch(j[k])):
            raise ConnectorError("bad_argument", f"package.json: bad {k}")
    if "private" in j and not isinstance(j["private"], bool):
        raise ConnectorError("bad_argument", "package.json: private must be true or false")
    dev = j.get("devDependencies")
    if not isinstance(dev, dict) or dev.get("@servicenow/sdk") is None:
        raise ConnectorError("bad_argument", "package.json: devDependencies must include @servicenow/sdk")
    for section in ("devDependencies", "dependencies"):
        if section not in j:
            continue
        if not isinstance(j[section], dict):
            raise ConnectorError("bad_argument", f"package.json: {section} must be an object")
        for dep, ver in j[section].items():
            if dep not in ALLOWED_DEPS:
                raise ConnectorError("bad_argument", "package.json: dependency not allowed: " + str(dep)[:60])
            if not isinstance(ver, str) or not _EXACT.fullmatch(ver):
                raise ConnectorError("bad_argument", f"package.json: {dep} needs an exact version like 1.2.3")
