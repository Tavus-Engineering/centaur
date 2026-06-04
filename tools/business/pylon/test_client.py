import importlib.util
from pathlib import Path
from typing import Any

_CLIENT_PATH = Path(__file__).with_name("client.py")
_SPEC = importlib.util.spec_from_file_location("pylon_client", _CLIENT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_pylon_client = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_pylon_client)
PylonClient = _pylon_client.PylonClient


class FakePylonClient(PylonClient):
    def __init__(self):
        super().__init__(api_key="test")
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        self.requests.append((method, endpoint, kwargs))
        if endpoint == "/issues/16412":
            return {"data": {"id": "iss_canonical", "number": 16412, "title": "Recording issue"}}
        if endpoint == "/issues/iss_canonical":
            return {"data": {"id": "iss_canonical", "number": 16412, "title": "Recording issue"}}
        if endpoint == "/issues/iss_canonical/messages":
            return {"data": [{"id": "msg_1", "body_html": "<p>Customer report</p>"}]}
        if endpoint == "/issues/iss_canonical/threads":
            return {"data": [{"id": "thr_1", "name": "Internal notes"}]}
        raise AssertionError(f"unexpected request: {method} {endpoint}")


def test_get_issue_context_resolves_issue_number_for_messages_and_threads():
    client = FakePylonClient()

    result = client.get_issue_context("#16412")

    assert result == {
        "issue": {"id": "iss_canonical", "number": 16412, "title": "Recording issue"},
        "messages": [{"id": "msg_1", "body_html": "<p>Customer report</p>"}],
        "threads": [{"id": "thr_1", "name": "Internal notes"}],
    }
    assert [request[:2] for request in client.requests] == [
        ("GET", "/issues/16412"),
        ("GET", "/issues/iss_canonical/messages"),
        ("GET", "/issues/iss_canonical/threads"),
    ]


def test_get_issue_messages_accepts_pylon_issue_url():
    client = FakePylonClient()

    result = client.get_issue_messages("https://app.usepylon.com/issues/16412?foo=bar")

    assert result == [{"id": "msg_1", "body_html": "<p>Customer report</p>"}]
    assert [request[:2] for request in client.requests] == [
        ("GET", "/issues/16412"),
        ("GET", "/issues/iss_canonical/messages"),
    ]


def test_get_issue_messages_uses_canonical_id_directly():
    client = FakePylonClient()

    result = client.get_issue_messages("iss_canonical")

    assert result == [{"id": "msg_1", "body_html": "<p>Customer report</p>"}]
    assert [request[:2] for request in client.requests] == [
        ("GET", "/issues/iss_canonical/messages"),
    ]
