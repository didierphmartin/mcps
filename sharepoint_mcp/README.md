# sharepoint_mcp

A small MCP server (JSON-RPC over HTTP, Python/FastAPI) that lets a workflow work in a SharePoint document library
through Microsoft Graph, signed in as a user (delegated permissions). It is the sibling of `outlook_mcp` and has the
same shape: the same sign-in flows, connection key and failure contract. It adds the folder and upload tools.

## Run

```
cp .env.example .env     # fill in SHAREPOINT_CLIENT_ID and SHAREPOINT_SECRET_KEY
./run.sh                 # creates .venv, installs requirements.txt, serves on :8771
.venv/bin/python -m pytest -q
```

`SHAREPOINT_MOCK_GRAPH=1` runs against an in-process mock of Microsoft (no Entra app needed).

## Environment

| Variable | Meaning |
| --- | --- |
| `SHAREPOINT_CLIENT_ID` | Entra app registration (required) |
| `SHAREPOINT_SECRET_KEY` | Fernet key that encrypts refresh tokens at rest (required; `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |
| `SHAREPOINT_PUBLIC_URL` | Public base URL of this server (https, or http://localhost); enables the browser sign-in (`/auth/start`, `/auth/callback`) |
| `SHAREPOINT_CLIENT_SECRET` | Only for a confidential app registration |
| `SHAREPOINT_SITE` | Default site, e.g. `contoso.sharepoint.com:/sites/Team` (tool arguments override) |
| `SHAREPOINT_LIBRARY` | Default document library name (tool arguments override) |
| `SHAREPOINT_PORT` | Default `8771` (`SHAREPOINT_HOST`, default `127.0.0.1`) |
| `SHAREPOINT_DB_PATH` | SQLite file; default `~/Documents/synergyAI/sharepoint_mcp.sqlite` |

## Entra permission

Delegated Microsoft Graph permission `Sites.ReadWrite.All` (plus `User.Read`, `offline_access`), with admin consent.
Add `http://localhost:8771/auth/callback` (or `<PUBLIC_URL>/auth/callback`) as a redirect URI for the browser sign-in,
and allow public client flows for the device-code sign-in.

## Tools

- `connect_start` / `connect_status`: sign in with a device code or in the browser. The connected status returns
  `connection_key` once and `credential_header` (`X-SharePoint-Key`): send the key in that header on every call.
- `whoami`: the connected account, once Microsoft confirms the sign-in still works (Graph `/me`).
- `ensure_folder(path)`: create the missing segments of a folder path, reuse existing ones (case-insensitive); a file
  with a segment's name is `invalid_argument`.
- `create_subfolder(parent, name)`: a new folder that never reuses a name (` (2)`, ` (3)` on a clash).
- `upload_file(folder, name, base64, conflict?)`: upload one file, `rename` (default) or `fail` on a name clash.
  Up to 4 MiB is a single PUT; larger files use a Graph upload session in 3.125 MiB chunks. Returns
  `{path, id, web_url, size}`.

A failing tool returns an MCP tool error (`isError`) whose text is `{"error": code, "message": ...}`; codes include
`not_connected`, `reconnect_needed`, `throttled`, `not_found`, `forbidden`, `network_error`, `graph_error`, `internal_error`.
