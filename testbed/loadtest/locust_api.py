"""Thin client for Locust's web API."""

import os
import time
from pathlib import Path

import requests

# A connection error is retried for about a minute before the ladder gives up,
# so a brief network or pod-routing blip does not end an hours-long run.
RETRIES = 12
RETRY_WAIT_S = 5


def default_url() -> str:
    return os.environ.get("LOCUST_URL", "http://localhost:8089")


class Locust:
    def __init__(self, base_url: str | None = None):
        self.base = (base_url or default_url()).rstrip("/")

    def _request(self, method, path: str, **kwargs) -> requests.Response:
        for attempt in range(RETRIES):
            try:
                r = method(f"{self.base}{path}", timeout=30, **kwargs)
                r.raise_for_status()
                return r
            except requests.exceptions.ConnectionError:
                if attempt == RETRIES - 1:
                    raise
                time.sleep(RETRY_WAIT_S)
        raise AssertionError("unreachable")

    def swarm(self, users: int, spawn_rate: float, fields: dict[str, str]) -> None:
        data = {"user_count": users, "spawn_rate": spawn_rate, "host": "http://unused", **fields}
        r = self._request(requests.post, "/swarm", data=data)
        if not r.json().get("success"):
            raise RuntimeError(f"swarm refused: {r.text}")

    def _stats(self) -> dict:
        return self._request(requests.get, "/stats/requests").json()

    def state(self) -> str:
        return self._stats()["state"]

    def user_count(self) -> int:
        return int(self._stats()["user_count"])

    def reset_stats(self) -> None:
        self._request(requests.get, "/stats/reset")

    def save_stats(self, path: Path) -> None:
        path.write_text(self._request(requests.get, "/stats/requests/csv").text)

    def save_failures(self, path: Path) -> None:
        path.write_text(self._request(requests.get, "/stats/failures/csv").text)

    def stop(self) -> None:
        self._request(requests.get, "/stop")
