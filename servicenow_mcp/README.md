# ServiceNow MCP server

MCP server (Python) that lets SynergyAI work the ServiceNow tasks assigned to it: find the next task, claim it,
note progress, then close it or hand it back to a human group. A second endpoint installs generated Fluent apps on a
dev or test instance. It replaces the PHP connector (`servicenow/`), with the same tools and answers.

## Settings (`.env`, first)

Copy `.env.example` to `.env` (chmod 600) and fill it in. `run.sh` reads it.

| Setting | Required | Where to find it |
|---|---|---|
| `SN_INSTANCE` | yes | Your instance URL, `https://<name>.service-now.com`. Or `mock` for the built-in fake instance (no other setting needed). |
| `SN_CLIENT_ID`, `SN_CLIENT_SECRET` | yes | Machine Identity Console → Inbound integrations → OAuth – Client credentials grant (see *ServiceNow setup*). |
| `SN_GROUP` | yes | The assignment group SynergyAI works for, e.g. `SynergyAI`. |
| `SN_TAG_PREFIX` | yes | The prefix of SynergyAI tasks' correlation display, e.g. `synergyai:`. |
| `SN_ENVIRONMENT` | no | `dev`, `test` or `prod` (default `prod`). Only dev and test allow deploying apps. |
| `SN_HOST`, `SN_PORT` | no | Where the server listens (default `127.0.0.1:8772`). |
| `SN_WAIT_INTERVAL_S`, `SN_WAIT_WINDOW_S` | no | How often and how long `wait_for_jobs` checks (defaults 5 and 120; both at most 140). |
| `SN_INSTALL_USER`, `SN_INSTALL_PASSWORD`, `SN_NPX`, `SN_DEPLOY_TOKEN` | deploy only | A user that may install apps, the full path of `npx`, and the token deploy callers must send. |

Values are read literally (quotes around a whole value are removed). A bad or missing setting does not stop the
server: every request answers `bad_config: …`, so SynergyAI's MCP test shows what to fix.

## Run

```
./run.sh
```

The first start creates `.venv` and installs `requirements.txt` (Python 3.10 or later; `SN_PYTHON` picks the
interpreter). Register `http://127.0.0.1:8772/mcp` in SynergyAI as the server named `servicenow`.

## Addresses

- `POST /mcp` (also `/`, `/jobs`, `/jobs/mcp`): the job tools.
- `POST /deploy` (also `/deploy/mcp`): `install_app`. Every call needs `Authorization: Bearer <SN_DEPLOY_TOKEN>`.

Requests must be JSON (`Content-Type: application/json`); a browser page may call only from localhost.

## Tools

`poll_jobs(tag?)`, `wait_for_jobs(tag?)`, `claim_job(task)`, `add_note(task, text)`, `complete_job(task, notes)`,
`hand_back(task, group, reason)`, `describe_item(key)`. They act only on tasks in `SN_GROUP` tagged
`SN_TAG_PREFIX…`. `wait_for_jobs` is the long poll for SynergyAI's runner: it answers `ready` as soon as a job exists,
or `timeout` after the wait window; it claims nothing. A failure is a tool error whose text is `<code>: <message>`
(`bad_argument`, `task_not_found`, `not_claimable`, `not_claimed`, `group_not_found`, `auth_failed`, `forbidden`,
`instance_unavailable`, …).

`install_app(scope, files)` writes the generated Fluent app (`package.json`, `now.config.json`, `src/fluent/**.ts`; at
most 2 MB; no `..`, absolute paths or symbolic links) to `var/deploy/<scope>/`, then runs `npm install` (first time
only), `now-sdk build` and `now-sdk install`. `package.json` must be what the generator writes. The SDK runs in its CI
mode, with the install credentials in that step's environment only (never in a command line). Node, npm and `now-sdk`
must be reachable; set `SN_NPX` to the full path of `npx`.

## The mock instance

`SN_INSTANCE=mock` serves `fixtures/mock.json`. It remembers claims, notes and completions in `var/mock-state.json`,
so a completed task stops coming back; `.venv/bin/python reset_mock.py` starts again from the fixture. Its tool calls
are logged to `log/calls.jsonl`.

## ServiceNow setup (once per instance)

1. Machine user (Identity type: Machine; leave Internal Integration User unticked, no password) with role `itil`.
2. Group `SynergyAI` (`/sys_user_group.do?sys_id=-1`).
3. System property `glide.oauth.inbound.client.credential.grant_type.enabled` = `true`. It may not exist yet: in the
   Global scope, open `/sys_properties_list.do` → New (type `true | false`). Not to be confused with
   `glide.oauth.inbound.ropc.grant_type.disabled`, which the search lands on when this one is missing.
4. Machine Identity Console → Inbound integrations → OAuth – Client credentials grant, OAuth application user =
   the machine user, scope `useraccount` → client ID and secret into `.env`.

## Code components

`components/` holds the three SynergyAI code components that drive ServiceNow jobs (`get_new_job`, `complete_job`,
`hand_back`). `python3 components_sql.py <user_id> > components.sql` prints the SQL that installs them; run it
yourself.

## Tests

`.venv/bin/python -m pytest` (no network). Components: `python3 -m unittest discover -s components/tests`.
