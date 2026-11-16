import requests

from loadtest import locust_api
from loadtest.locust_api import Locust


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.text = "csv"

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_retries_transient_connection_errors(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.exceptions.ConnectionError("refused")
        return FakeResponse({"state": "running", "user_count": 5})

    monkeypatch.setattr(locust_api.requests, "get", fake_get)
    monkeypatch.setattr(locust_api.time, "sleep", lambda s: None)
    assert Locust("http://x").state() == "running"
    assert calls["n"] == 3


def test_gives_up_after_retries(monkeypatch):
    def fake_get(url, timeout):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(locust_api.requests, "get", fake_get)
    monkeypatch.setattr(locust_api.time, "sleep", lambda s: None)
    try:
        Locust("http://x").state()
    except requests.exceptions.ConnectionError:
        return
    raise AssertionError("expected ConnectionError")
