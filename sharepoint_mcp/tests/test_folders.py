import dataclasses

import pytest

from auth import Auth
from drive import DriveService, safe_name
from graph import GraphClient, TokenSource
from store import Store

SITE = "contoso.sharepoint.com:/sites/Mail"


def service(mock, http, cfg, site=SITE, library="Documents"):
    tokens = mock._tokens_response().json()
    store = Store(cfg.db_path, cfg.secret_key)
    store.save_connection("key-1", mock.account, mock.tenant, tokens["refresh_token"])
    cfg = dataclasses.replace(cfg, site=site, library=library)
    graph_for = lambda key: GraphClient(http, cfg.graph_base, TokenSource(Auth(http, cfg), store, key))
    return DriveService(graph_for, store, cfg)


def test_ensure_folder_creates_missing_segments(mock, http, cfg):
    drive = mock.add_library(SITE, "Documents")
    r = service(mock, http, cfg).ensure_folder("key-1", {"path": "alice@x.com/2026"})
    assert r["path"] == "alice@x.com/2026" and r["id"]
    assert r["created"] == ["alice@x.com", "alice@x.com/2026"]
    assert mock.folder_paths(drive) == ["alice@x.com", "alice@x.com/2026"]


def test_ensure_folder_reuses_existing_case_insensitive(mock, http, cfg):
    drive = mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    first = svc.ensure_folder("key-1", {"path": "Alice/Inbox"})
    again = svc.ensure_folder("key-1", {"path": "alice/INBOX"})
    assert again["created"] == [] and again["id"] == first["id"]
    assert mock.folder_paths(drive) == ["Alice", "Alice/Inbox"]
    more = svc.ensure_folder("key-1", {"path": "alice/inbox/new"})
    assert more["created"] == ["alice/inbox/new"]


def test_create_subfolder_suffixes_on_clash(mock, http, cfg):
    mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    svc.ensure_folder("key-1", {"path": "Alice"})
    paths = [svc.create_subfolder("key-1", {"parent": "alice", "name": "X"})["path"] for _ in range(3)]
    assert paths == ["alice/X", "alice/X (2)", "alice/X (3)"]


def test_create_subfolder_cleans_name_and_needs_parent(mock, http, cfg):
    mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    assert svc.create_subfolder("key-1", {"parent": "", "name": "a/b: c"})["path"] == "ab c"
    assert svc.create_subfolder("key-1", {"parent": "nope", "name": "x"})["error"] == "not_found"


def test_safe_name_strips_forbidden_and_caps_length():
    assert safe_name('a:b*c?"d<e>f|g/h\\i. ') == "abcdefghi"
    assert len(safe_name("x" * 300)) == 120
    assert safe_name("a   b\x01\tc") == "a bc" and safe_name(' ?. ') == "_"


def test_unknown_library_is_not_found(mock, http, cfg):
    mock.add_library(SITE, "Documents")
    r = service(mock, http, cfg, library="Nope").ensure_folder("key-1", {"path": "a"})
    assert r["error"] == "not_found" and "Nope" in r["message"]


def test_args_override_env_library(mock, http, cfg):
    mock.add_library(SITE, "Documents")
    other = mock.add_library("contoso.sharepoint.com:/sites/Other", "Reports")
    r = service(mock, http, cfg).ensure_folder("key-1", {"path": "q1", "site": "contoso.sharepoint.com:/sites/Other",
                                                          "library": "reports"})
    assert r["created"] == ["q1"] and mock.folder_paths(other) == ["q1"]


def test_missing_config_is_invalid_argument_naming_env_var(mock, http, cfg):
    assert "SHAREPOINT_SITE" in service(mock, http, cfg, site="").ensure_folder("key-1", {"path": "a"})["message"]
    r = service(mock, http, cfg, library="").create_subfolder("key-1", {"parent": "", "name": "a"})
    assert r["error"] == "invalid_argument" and "SHAREPOINT_LIBRARY" in r["message"]


def test_drive_lookup_is_cached(mock, http, cfg):
    mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    svc.ensure_folder("key-1", {"path": "a"})
    svc.ensure_folder("key-1", {"path": "b"})
    assert len([r for r in mock.requests if r[1].endswith("/drives")]) == 1


def test_special_characters_are_percent_encoded(mock, http, cfg):
    drive = mock.add_library(SITE, "Documents")
    r = service(mock, http, cfg).ensure_folder("key-1", {"path": "2026-10-22 - Ann #1 & Bob 100%"})
    assert r["created"] and mock.folder_paths(drive) == ["2026-10-22 - Ann #1 & Bob 100%"]


def test_mock_honours_conflict_behavior_for_folders(mock, http, cfg):
    import httpx
    drive = mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    svc.ensure_folder("key-1", {"path": "Alice/X"})
    graph = svc._graph("key-1")
    from graph import GraphError
    import pytest
    with pytest.raises(GraphError) as e:
        graph.post(f"/drives/{drive}/root:/Alice:/children", {"name": "x", "folder": {}, "@microsoft.graph.conflictBehavior": "fail"})
    assert e.value.status == 409
    assert graph.post(f"/drives/{drive}/root:/Alice:/children", {"name": "X", "folder": {}, "@microsoft.graph.conflictBehavior": "rename"})["name"] == "X 1"
    assert graph.post(f"/drives/{drive}/root:/Alice:/children", {"name": "X", "folder": {}})["name"] == "X 2"


def test_ensure_folder_rejects_a_file_with_the_folders_name(mock, http, cfg):
    import base64
    mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    svc.upload_file("key-1", {"folder": "Alice", "name": "mail1", "base64": base64.b64encode(b"x").decode()})
    r = svc.ensure_folder("key-1", {"path": "Alice/mail1/sub"})
    assert r["error"] == "invalid_argument" and "exists as a file" in r["message"]
    assert svc.create_subfolder("key-1", {"parent": "Alice/mail1", "name": "s"})["error"] == "invalid_argument"


def test_suffixed_subfolder_survives_the_length_cap_so_uploads_land_in_it(mock, http, cfg):
    import base64
    drive = mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    svc.ensure_folder("key-1", {"path": "Alice"})
    name = "2026-10-22 - notifications-noreply@accounts.example-company.com - " + "x" * 64   # 130 characters
    first = svc.create_subfolder("key-1", {"parent": "Alice", "name": name})["path"]
    second = svc.create_subfolder("key-1", {"parent": "Alice", "name": name})["path"]
    assert second != first and second.endswith(" (2)") and len(second.split("/")[-1]) <= 120
    r = svc.upload_file("key-1", {"folder": second, "name": "a.pdf", "base64": base64.b64encode(b"x").decode()})
    assert r["path"] == f"{second}/a.pdf"
    assert mock.files(drive) == {f"{second}/a.pdf": b"x"}


def test_apostrophe_and_accents_round_trip(mock, http, cfg):
    import base64
    drive = mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    assert svc.ensure_folder("key-1", {"path": "Élodie/L'offre"})["path"] == "Élodie/L'offre"
    sub = svc.create_subfolder("key-1", {"parent": "Élodie/L'offre", "name": "2026-10-22 - Re: l'été à Zürich"})
    assert sub["path"] == "Élodie/L'offre/2026-10-22 - Re l'été à Zürich"
    r = svc.upload_file("key-1", {"folder": sub["path"], "name": "Reçu d'achat.pdf", "base64": base64.b64encode(b"x").decode()})
    assert r["path"] == f"{sub['path']}/Reçu d'achat.pdf"
    assert mock.folder_paths(drive) == ["Élodie", "Élodie/L'offre", sub["path"]]
    assert mock.files(drive) == {r["path"]: b"x"}
    again = svc.ensure_folder("key-1", {"path": "élodie/l'OFFRE"})
    assert again["created"] == []
