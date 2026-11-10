import httpx
import pytest

from config import AppConfig
from mock_graph import MockGraph


@pytest.fixture
def mock():
    return MockGraph()


@pytest.fixture
def http(mock):
    return httpx.Client(transport=httpx.MockTransport(mock.handler))


@pytest.fixture
def cfg(tmp_path):
    return AppConfig(client_id="cid", secret_key=AppConfig.new_secret_key(), db_path=str(tmp_path / "s.sqlite"),
                     public_url="https://synergy.example.com/sharepoint")
