# SynergyAI MCP servers

MCP servers used by [SynergyAI](https://synergyaichat.com): chat, workflows and automations call them as tools. Each
folder is one server, with a `synergyai-mcp.json` manifest that says how to install it, start it and which settings
it needs, so SynergyAI can import it from this repository.

## What is MCP?

The **Model Context Protocol** (MCP) is an open protocol that lets AI applications use external tools and data in a
standard way. A server lists its tools (name, description, input schema); the application's model picks one, and the
application calls it with JSON-RPC 2.0 messages over a transport such as streamable HTTP. One server works with every
MCP client, and one client can use any number of servers.

- Introduction: https://modelcontextprotocol.io
- Specification: https://modelcontextprotocol.io/specification/latest

## The servers

### PHP (served by Apache)

The server is `mcp.php` in its folder, reached at `http://<host>/<folder>/mcp.php`. Several of them display an
interactive widget in the chat (`mcp-app.html`) instead of returning plain text.

| Folder | What it does | Tools | Settings |
|---|---|---|---|
| `arxiv` | Search arXiv preprints, read a paper's metadata or full text, find related papers | `search_arxiv`, `get_arxiv_paper`, `find_similar_papers`, `list_arxiv_categories`, `fetch_paper_html` | none |
| `googlemaps` | Shows a live Google Map in the chat: a place, directions between two locations, nearby places | `show-map`, `show-directions`, `search-places` | `GOOGLE_MAPS_API_KEY` |
| `tradingview` | Shows a live TradingView chart for a stock, crypto or forex symbol | `show-financial-chart` | none |
| `image-server` | Opens a form in the chat to generate an image with Google Gemini | `generate-image` | `GEMINI_API_KEY` |
| `video-server` | Opens a form in the chat to generate a video with Google Veo or xAI Grok Imagine | `generate-video` | `GEMINI_API_KEY` and/or `GROK_API_KEY` |

### Python (FastAPI, streamable HTTP)

Each runs as its own process in its own virtual environment, answering at `http://127.0.0.1:<port>/mcp`.

| Folder | What it does | Tools | Default port |
|---|---|---|---|
| `outlook_mcp` | Reads and files mail in a Microsoft 365 or Outlook.com mailbox through Microsoft Graph: new mail, attachments as text, a mail as PDF, move, forward, wait for new mail | `connect_start`, `connect_status`, `whoami`, `list_folders`, `poll_new_mail`, `get_attachment`, `mail_to_pdf`, `move_mail`, `forward_mail`, `wait_for_new` | 8770 |
| `sharepoint_mcp` | Works in a SharePoint document library through Microsoft Graph: make folders, upload files | `connect_start`, `connect_status`, `whoami`, `ensure_folder`, `create_subfolder`, `upload_file` | 8771 |
| `langfs` | Reads documents from a folder or cloud storage through LangChain loaders, one at a time as text, read-only | `list_providers`, `read_next`, `reset`, `list_files`, `read_file` | 8077 |
| `mcp_qrant` | Vector store: stores text chunks and finds them by meaning (Qdrant, local or remote; pgvector) | `list_providers`, `list_embeddings`, `test_connection`, `store`, `find` | 8008 |

`outlook_mcp` and `sharepoint_mcp` need an Entra ID app registration; their READMEs explain where each setting is found.

## Installing a server

**With SynergyAI (Docker edition):** import it from this repository; SynergyAI reads the manifest, asks for the
settings, installs the server and registers it.

**By hand:**

- PHP: copy the folder into your web server's document root, copy `.env.example` to `.env` (when there is one) and
  fill in the keys.
- Python: in the folder, run the manifest's `install` command (`python3 -m venv .venv && .venv/bin/pip install -r
  requirements.txt`), put the settings in `.env`, then run its `start` command (`./run.sh`, or
  `.venv/bin/python server.py`).

Then add the server's address in SynergyAI under Settings → MCP servers.

## The manifest (`synergyai-mcp.json`)

| Field | Meaning |
|---|---|
| `name`, `description` | the server's name and what it does |
| `runtime` | `php` or `python` |
| `entry` | PHP: the file that answers MCP requests (`mcp.php`) |
| `install`, `start` | Python: run once to install, then to start the server (in its folder) |
| `env` | the settings: `name`, `label`, `required`, `secret`, `default`; when absent, read from `.env.example` |
| `include`, `exclude` | which files are installed (tests, logs, `.env` and virtual environments never are) |

Private settings live in each server's `.env`, which is never committed.
