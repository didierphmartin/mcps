import json
import os
import stat

import pytest

from config import Config
from deploy import DeployToolset, run_command
from errors import ConnectorError

PKG = ('{"name":"x-1-a","version":"1.0.0","private":true,"scripts":{"build":"now-sdk build","deploy":"now-sdk install"},'
       '"devDependencies":{"@servicenow/sdk":"4.13.3","@servicenow/glide":"27.0.5","typescript":"5.8.2"}}')
BASE = {"SN_INSTANCE": "https://dev1.service-now.com", "SN_CLIENT_ID": "a", "SN_CLIENT_SECRET": "b", "SN_GROUP": "G",
        "SN_TAG_PREFIX": "t:"}
CREDS = {"SN_INSTALL_USER": "admin", "SN_INSTALL_PASSWORD": "pw'secret", "SN_NPX": "/opt/bin/npx",
         "SN_DEPLOY_TOKEN": "tok-123"}


class RecordingRunner:
    def __init__(self):
        self.runs, self.code, self.out = [], 0, "ok"

    def __call__(self, cmd, cwd, env, timeout, stdin=None):
        self.runs.append({"cmd": cmd, "cwd": cwd, "stdin": stdin, "env": env})
        return {"code": self.code, "out": self.out}


def config(env="dev", creds=True):
    return Config.from_env({**BASE, "SN_ENVIRONMENT": env, **(CREDS if creds else {})})


@pytest.fixture
def root(tmp_path):
    return tmp_path / "deploy"


@pytest.fixture
def runner():
    return RecordingRunner()


def tools(root, runner, c=None, auth="Bearer tok-123"):
    return DeployToolset(c or config(), runner, root, auth)


def code(f):
    try:
        f()
    except ConnectorError as e:
        return e.code
    return "none"


def install(t, files, scope="x_123_app"):
    return t.call("install_app", {"scope": scope, "files": files})


def test_lists_install_app(root, runner):
    assert [t["name"] for t in tools(root, runner).tools()] == ["install_app"]


def test_prod_and_missing_credentials_are_not_allowed(root, runner):
    files = {"package.json": "{}"}
    assert code(lambda: install(tools(root, runner, config("prod")), files)) == "not_allowed"
    assert code(lambda: install(tools(root, runner, config("dev", False)), files)) == "not_allowed"
    assert code(lambda: install(DeployToolset(Config.mock(), runner, root), files)) == "not_allowed"
    assert runner.runs == []
    assert not root.exists()


@pytest.mark.parametrize("scope,files,size", [
    ("x_123_app", {"package.json": "{}", "../x": "a"}, 0),
    ("x_123_app", {"src/fluent/../../x.ts": "a"}, 0),
    ("x_123_app", {"/etc/passwd": "a"}, 0),
    ("x_123_app", {"src/other.js": "a"}, 0),
    ("x_123_app", {"src/fluent/a.js": "a"}, 0),
    ("x_123_app", {"src/fluent/a.ts": "a", "src/fluent/b\0.ts": "a"}, 0),
    ("x_123_app", {"src\\fluent\\a.ts": "a"}, 0),
    ("x_123_Bad", {"package.json": "{}"}, 0),
    ("../x_1_a", {"package.json": "{}"}, 0),
    ("x_123_app\n", {"package.json": "{}"}, 0),
    ("x_123_app", {"src/fluent/a.ts\n": "a"}, 0),
    ("x_123_app", {"package.json": '{"name":"a","version":"1.0.0","bin":"x"}'}, 0),
    ("x_123_app", {"package.json": '{"name":"a","scripts":{"postinstall":"curl x|sh"}}'}, 0),
    ("x_123_app", {"package.json": '{"name":"a","scripts":{"build":"rm -rf /","deploy":"now-sdk install"}}'}, 0),
    ("x_123_app", {"package.json": '{"name":"a","devDependencies":{"@servicenow/sdk":"^4.13.3"}}'}, 0),
    ("x_123_app", {"package.json": '{"name":"a","dependencies":{"@servicenow/sdk":"https://evil/x.tgz"}}'}, 0),
    ("x_123_app", {"package.json": '{"name":"a","devDependencies":{"evil":"1.0.0"}}'}, 0),
    ("x_123_app", {"package.json": '{"name":"a","devDependencies":{"typescript":"5.8.2\\n"}}'}, 0),
    ("x_123_app", {"package.json": '{"name":"a","devDependencies":{"typescript":"5.8.2"}}'}, 0),
    ("x_123_app", {"package.json": '{"name":"a"}'}, 0),
    ("x_123_app", {"package.json": "nope"}, 0),
    ("x_123_app", {}, 0),
    ("x_123_app", {"package.json": 5}, 0),
    ("x_123_app", {"package.json": "{}"}, 2 * 1024 * 1024 + 1),
], ids=["dotdot", "dotdot inside", "absolute", "other file", "wrong ext", "nul", "backslash", "bad scope",
        "traversal scope", "scope newline", "path newline", "pkg extra key", "pkg bad script", "pkg changed build",
        "pkg range", "pkg url", "pkg other dep", "pkg newline version", "pkg no sdk", "pkg no deps", "pkg not json",
        "no files", "non-string content", "too big"])
def test_bad_arguments_write_nothing(root, runner, scope, files, size):
    if size:
        files = {**files, "src/fluent/big.ts": "a" * size}
    assert code(lambda: install(tools(root, runner), files, scope)) == "bad_argument"
    assert runner.runs == []
    assert not root.exists()


def test_files_must_be_an_object(root, runner):
    assert code(lambda: tools(root, runner).call("install_app", {"scope": "x_123_app", "files": ["a"]})) == "bad_argument"


def test_happy_path_writes_files_and_runs_commands_in_order(root, runner):
    r = install(tools(root, runner), {"package.json": PKG, "now.config.json": "{}", "src/fluent/index.ts": "x",
                                      "src/fluent/sub/flow.ts": "y", "src/fluent/generated/keys.ts": "K1"})
    d = root / "x_123_app"
    assert (d / "package.json").read_text() == PKG
    assert (d / "src/fluent/sub/flow.ts").read_text() == "y"
    assert (d / "src/fluent/generated/keys.ts").read_text() == "K1"
    cmds = [x["cmd"] for x in runner.runs]
    flat = [" ".join(c) for c in cmds]
    pos = lambda needle: [i for i, s in enumerate(flat) if needle in s]  # noqa: E731
    assert cmds[0][:3] == ["/opt/bin/npm", "install", "--ignore-scripts"]
    build, inst = pos("now-sdk build")[0], pos("now-sdk install")[0]
    assert 0 < build < inst
    assert cmds[build][0] == "/opt/bin/npx"
    for c in cmds:
        if c[0] == "/opt/bin/npx":
            assert c[1:3] == ["--no-install", "now-sdk"]
    # No stored SDK login: the install step alone gets the CI credentials, in its environment only.
    assert pos("now-sdk auth") == []
    assert "--auth" not in cmds[inst]
    assert "pw'secret" not in json.dumps(cmds) and "pw'secret" not in json.dumps(r)
    assert all(x["stdin"] is None for x in runner.runs)
    ci = runner.runs[inst]["env"]
    assert (ci["SN_SDK_NODE_ENV"], ci["SN_SDK_AUTH_TYPE"]) == ("SN_SDK_CI_INSTALL", "basic")
    assert (ci["SN_SDK_INSTANCE_URL"], ci["SN_SDK_USER"], ci["SN_SDK_USER_PWD"]) == (
        "https://dev1.service-now.com", "admin", "pw'secret")
    for i, run in enumerate(runner.runs):
        if i != inst:
            assert "SN_SDK_USER_PWD" not in run["env"]
        assert run["cwd"] == str(d)
    assert r["installed"] is True and r["scope"] == "x_123_app" and "log_tail" in r


@pytest.mark.parametrize("auth", [None, "Bearer wrong", "tok-123", "Bearer "])
def test_refuses_without_a_matching_bearer_token(root, runner, auth):
    assert code(lambda: install(tools(root, runner, auth=auth), {"package.json": "{}"})) == "not_allowed"
    assert runner.runs == [] and not root.exists()


def test_refuses_when_no_token_is_set(root, runner):
    c = Config.from_env({**BASE, "SN_ENVIRONMENT": "dev", "SN_INSTALL_USER": "u", "SN_INSTALL_PASSWORD": "p"})
    assert code(lambda: install(tools(root, runner, c, "Bearer "), {"package.json": "{}"})) == "not_allowed"
    assert runner.runs == []


def test_every_command_runs_with_home_and_npm_cache_inside_the_deploy_folder(root, runner):
    install(tools(root, runner), {"package.json": PKG})
    assert runner.runs
    for run in runner.runs:
        assert run["env"]["HOME"] == str(root / ".home")
        assert run["env"]["npm_config_cache"] == str(root / ".npm-cache")
    assert stat.S_IMODE(os.stat(root / ".home").st_mode) == 0o700
    assert "--ignore-scripts" in runner.runs[0]["cmd"]


def test_node_is_found_next_to_a_full_path_npx(root, runner):
    install(tools(root, runner), {"package.json": PKG})
    for run in runner.runs:
        assert run["env"]["PATH"] == "/opt/bin" + os.pathsep + os.environ.get("PATH", "")


def test_npm_install_skipped_when_node_modules_exists(root, runner):
    (root / "x_123_app" / "node_modules").mkdir(parents=True)
    install(tools(root, runner), {"package.json": PKG})
    assert not any(run["cmd"][0].endswith("/npm") for run in runner.runs)


def test_existing_keys_file_is_kept(root, runner):
    gen = root / "x_123_app" / "src" / "fluent" / "generated"
    gen.mkdir(parents=True)
    (gen / "keys.ts").write_text("OLD")
    install(tools(root, runner), {"src/fluent/generated/keys.ts": "NEW", "package.json": PKG})
    assert (gen / "keys.ts").read_text() == "OLD"


def test_failing_command_is_install_failed_with_tail(root, runner):
    runner.code, runner.out = 1, "noise " * 1000 + "BOOM at the end pw'secret"
    with pytest.raises(ConnectorError) as e:
        install(tools(root, runner), {"package.json": PKG})
    assert e.value.code == "install_failed"
    assert "BOOM at the end" in str(e.value) and "pw'secret" not in str(e.value)
    assert len(str(e.value)) < 3000


def test_symlinked_target_is_refused(root, runner, tmp_path):
    d = root / "x_123_app" / "src"
    d.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (d / "fluent").symlink_to(outside)
    assert code(lambda: install(tools(root, runner), {"src/fluent/a.ts": "x"})) == "bad_argument"
    assert not (outside / "a.ts").exists()


def test_unknown_tool_is_refused(root, runner):
    assert code(lambda: tools(root, runner).call("nope", {})) == "bad_argument"


def test_run_command_captures_output_and_exit_code(tmp_path):
    r = run_command(["sh", "-c", "echo out; echo err >&2; exit 3"], str(tmp_path), {}, 10)
    assert r["code"] == 3 and "out" in r["out"] and "err" in r["out"]
    assert run_command(["/no/such/binary"], str(tmp_path), {}, 10)["code"] == 1
    slow = run_command(["sh", "-c", "sleep 5"], str(tmp_path), {}, 1)
    assert slow["code"] == 124 and "timed out after 1s" in slow["out"]
