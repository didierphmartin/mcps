"""Forget the mock instance's claims, notes and completions: the next request starts from fixtures/mock.json."""
from server import APP_DIR, mock_state_path
from fixture_backend import FixtureBackend

if __name__ == "__main__":
    FixtureBackend.reset_state(mock_state_path(APP_DIR))
    print("mock state reset: the next poll starts from fixtures/mock.json")
