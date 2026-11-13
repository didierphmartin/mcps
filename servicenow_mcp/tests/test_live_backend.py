import json
import os
import stat
from urllib.parse import parse_qs, unquote

import pytest

from config import Config
from errors import ConnectorError
from live_backend import LiveBackend, TokenProvider

SECRET = "SECRET-xyz-123"
CONFIG = Config.from_env({"SN_INSTANCE": "https://dev1.service-now.com", "SN_CLIENT_ID": "cid",
                          "SN_CLIENT_SECRET": SECRET, "SN_GROUP": "SynergyAI", "SN_TAG_PREFIX": "synergyai:"})


def ok(token, expires=1799):
    return {"status": 200, "body": json.dumps({"access_token": token, "token_type": "Bearer", "expires_in": expires})}


class TestTokenProvider:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.cache = tmp_path / "cache"
        self.calls, self.responses, self.now = [], [], 1000

    def provider(self):
        def transport(m, u, h, b):
            self.calls.append((m, u, b))
            return self.responses.pop(0) if self.responses else {"status": 500, "body": ""}
        return TokenProvider(CONFIG, transport, self.cache, lambda: self.now)

    def test_fetches_with_client_credentials_and_caches(self):
        self.responses = [ok("tok1")]
        p = self.provider()
        assert p.token() == "tok1" and p.token() == "tok1"
        assert len(self.calls) == 1
        m, u, b = self.calls[0]
        assert (m, u) == ("POST", "https://dev1.service-now.com/oauth_token.do")
        assert {k: v[0] for k, v in parse_qs(b).items()} == {"grant_type": "client_credentials", "client_id": "cid",
                                                              "client_secret": SECRET}
        assert stat.S_IMODE(os.stat(self.cache / "token.json").st_mode) == 0o600
        assert self.provider().token() == "tok1", "a new provider reuses the cache file"
        assert len(self.calls) == 1

    def test_refreshes_near_expiry_and_after_invalidate(self):
        self.responses = [ok("tok1", 100), ok("tok2"), ok("tok3")]
        p = self.provider()
        assert p.token() == "tok1"
        self.now += 50
        assert p.token() == "tok2"
        p.invalidate()
        assert p.token() == "tok3"

    @pytest.mark.parametrize("resp,code", [
        ({"status": 401, "body": '{"error":"access_denied"}'}, "auth_failed"),
        ({"status": 200, "body": "<html>Your instance is hibernating</html>"}, "instance_unavailable"),
        ({"status": 503, "body": ""}, "instance_unavailable"),
    ])
    def test_failures_never_echo_the_secret(self, resp, code):
        self.responses = [resp]
        with pytest.raises(ConnectorError) as e:
            self.provider().token()
        assert e.value.code == code
        assert SECRET not in str(e.value)


ROW = {"sys_id": "f" * 32, "number": "SCTASK0010002", "state": "1", "active": "true", "short_description": "Test",
       "correlation_display": "synergyai:test-playbook", "assignment_group.name": "SynergyAI", "request_item": "e" * 32,
       "request_item.number": "RITM0010001", "request_item.cat_item": "c0ffee", "correlation_id": "okta@2",
       "request_item.cat_item.name": "Standard Laptop", "request_item.requested_for.user_name": "jane.doe"}


class TestLiveBackend:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path
        self.calls, self.responses, self.token_count = [], [], 0

    def backend(self):
        def transport(m, u, h, b):
            if u.endswith("/oauth_token.do"):
                self.token_count += 1
                return {"status": 200, "body": json.dumps({"access_token": f"TOKEN{self.token_count}", "expires_in": 1799})}
            self.calls.append({"method": m, "url": unquote(u), "headers": h, "body": b})
            return self.responses.pop(0) if self.responses else {"status": 200, "body": '{"result":[]}'}
        cache = self.tmp / f"cache{len(list(self.tmp.iterdir()))}"
        return LiveBackend(CONFIG, TokenProvider(CONFIG, transport, cache), transport)

    def test_poll_query_and_normalization(self):
        self.responses = [{"status": 200, "body": json.dumps({"result": [ROW]})}]
        t = self.backend().find_oldest_open_task("SynergyAI", "synergyai:okta")
        url = self.calls[0]["url"]
        assert url.startswith("https://dev1.service-now.com/api/now/table/sc_task?")
        assert ("sysparm_query=active=true^assignment_group.name=SynergyAI^correlation_displaySTARTSWITHsynergyai:okta"
                "^state=1^ORDERBYsys_created_on") in url
        assert "sysparm_limit=1" in url
        assert self.calls[0]["headers"]["Authorization"] == "Bearer TOKEN1"
        assert "correlation_id" in url and "request_item.cat_item," in url + ","
        assert (t["catalog_item_id"], t["correlation_id"], t["state"], t["active"]) == ("c0ffee", "okta@2", 1, True)
        assert (t["assignment_group"], t["request_item_number"], t["request_item"]) == ("SynergyAI", "RITM0010001", "e" * 32)

    def test_query_values_are_percent_encoded(self):
        b = self.backend()
        seen = []
        b.transport = lambda m, u, h, body: (seen.append(u), {"status": 200, "body": '{"result":[]}'})[1]
        b.find_group_sys_id("Service Desk")
        assert "name%3DService%20Desk%5Eactive%3Dtrue" in seen[0]   # space as %20, like PHP's RFC 3986 encoding

    def test_get_task_by_sys_id_and_number(self):
        self.responses = [{"status": 200, "body": json.dumps({"result": ROW})},
                          {"status": 404, "body": '{"error":{"message":"No Record found"}}'},
                          {"status": 200, "body": json.dumps({"result": [ROW]})}]
        b = self.backend()
        assert b.get_task("f" * 32)["number"] == "SCTASK0010002"
        assert f"/api/now/table/sc_task/{'f' * 32}?" in self.calls[0]["url"]
        assert b.get_task("0" * 32) is None
        assert b.get_task("SCTASK0010002")["number"] == "SCTASK0010002"
        assert "sysparm_query=number=SCTASK0010002" in self.calls[2]["url"]

    def test_answers_update_and_group(self):
        self.responses = [
            {"status": 200, "body": json.dumps({"result": [{"sc_item_option.item_option_new.name": "email",
                                                            "sc_item_option.item_option_new.question_text": "Email",
                                                            "sc_item_option.value": "jane@acme.com"}]})},
            {"status": 200, "body": '{"result":{"sys_id":"x"}}'},
            {"status": 200, "body": json.dumps({"result": [{"sys_id": "d" * 32}]})},
        ]
        b = self.backend()
        assert b.get_answers("e" * 32) == [{"name": "email", "label": "Email", "value": "jane@acme.com"}]
        assert f"sc_item_option_mtom?sysparm_query=request_item={'e' * 32}" in self.calls[0]["url"]
        b.update_task("f" * 32, {"state": 2, "work_notes": "Claimed by SynergyAI."})
        assert self.calls[1]["method"] == "PATCH"
        assert json.loads(self.calls[1]["body"]) == {"state": "2", "work_notes": "Claimed by SynergyAI."}
        assert b.find_group_sys_id("Service Desk") == "d" * 32
        assert "sys_user_group?sysparm_query=name=Service Desk" in self.calls[2]["url"]

    def test_describe_item_queries_and_converts_mandatory(self):
        item_id = "d" * 32
        self.responses = [
            {"status": 200, "body": json.dumps({"result": [{"cat_item": item_id, "default_value": "okta-reset@3"}]})},
            {"status": 200, "body": json.dumps({"result": [{"name": "user_email", "type": "6", "mandatory": "true"},
                                                           {"name": "reason", "type": "2", "mandatory": "false"}]})},
            {"status": 200, "body": json.dumps({"result": {"name": "Okta password reset"}})},
        ]
        r = self.backend().describe_item("okta-reset")
        assert "name=synergyai_automation^default_valueSTARTSWITHokta-reset@" in self.calls[0]["url"]
        assert f"cat_item={item_id}^name!=synergyai_automation^ORDERBYorder" in self.calls[1]["url"]
        assert f"/api/now/table/sc_cat_item/{item_id}" in self.calls[2]["url"]
        assert r == {"sys_id": item_id, "name": "Okta password reset", "version": 3, "variables": [
            {"name": "user_email", "type": "6", "mandatory": True}, {"name": "reason", "type": "2", "mandatory": False}]}
        self.responses = [{"status": 200, "body": '{"result":[]}'}]
        assert self.backend().describe_item("other") is None

    def test_describe_item_forbidden(self):
        self.responses = [{"status": 403, "body": "{}"}]
        with pytest.raises(ConnectorError) as e:
            self.backend().describe_item("okta-reset")
        assert e.value.code == "forbidden"

    def test_retries_once_with_a_fresh_token_on_401(self):
        self.responses = [{"status": 401, "body": "{}"}, {"status": 200, "body": '{"result":[]}'}]
        assert self.backend().find_oldest_open_task("SynergyAI", "synergyai:") is None
        assert self.token_count == 2
        assert self.calls[1]["headers"]["Authorization"] == "Bearer TOKEN2"

    @pytest.mark.parametrize("resps,code", [
        ([{"status": 401, "body": "{}"}, {"status": 401, "body": "{}"}], "auth_failed"),
        ([{"status": 403, "body": "{}"}], "forbidden"),
        ([{"status": 500, "body": "oops"}], "instance_unavailable"),
        ([{"status": 200, "body": "<html>Instance hibernating</html>"}], "instance_unavailable"),
    ])
    def test_error_mapping(self, resps, code):
        self.responses = resps
        with pytest.raises(ConnectorError) as e:
            self.backend().find_oldest_open_task("SynergyAI", "synergyai:")
        assert e.value.code == code
        assert SECRET not in str(e.value) and "TOKEN" not in str(e.value)

    def test_exact_tag_query_and_active_group_lookup(self):
        b = self.backend()
        b.find_oldest_open_task("SynergyAI", "synergyai:okta-reset", True)
        assert "^correlation_display=synergyai:okta-reset^" in self.calls[0]["url"]
        b.find_group_sys_id("Service Desk")
        assert "sysparm_query=name=Service Desk^active=true" in self.calls[1]["url"]
