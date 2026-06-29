"""Read-only Tavus public API client."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from centaur_sdk import secret

_ENVIRONMENTS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "prod": (
        "https://tavusapi.com/v2",
        "TAVUS_PROD_API_KEY",
        ("TAVUS_PROD_PUBLIC_API_BASE_URL",),
    ),
    "test": (
        "https://test.rqh.tavusapi.com/v2",
        "TAVUS_STAGING_API_KEY",
        ("TAVUS_TEST_PUBLIC_API_BASE_URL", "TAVUS_STAGING_PUBLIC_API_BASE_URL"),
    ),
    "stg": (
        "https://stg.rqh.tavusapi.com/v2",
        "TAVUS_STG_API_KEY",
        ("TAVUS_STG_PUBLIC_API_BASE_URL",),
    ),
}
_ENV_ALIASES = {
    "live": "prod",
    "production": "prod",
    "prod": "prod",
    "dev": "test",
    "local": "test",
    "staging": "test",
    "test": "test",
    "stage": "stg",
    "stg": "stg",
}
_ALLOWED_HOSTS = {
    "tavusapi.com",
    "test.rqh.tavusapi.com",
    "stg.rqh.tavusapi.com",
}


def _optional_config(name: str) -> str:
    value = secret(name, "").strip()
    return "" if value == name else value


class TavusApiClient:
    """Read-only client for the Tavus public API."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def _environment(self, env: str) -> tuple[str, str, tuple[str, ...]]:
        normalized = _ENV_ALIASES.get((env or "prod").strip().lower())
        if not normalized:
            allowed = ", ".join(sorted(_ENV_ALIASES))
            raise RuntimeError(f"Unsupported Tavus env {env!r}. Use one of: {allowed}.")
        return _ENVIRONMENTS[normalized]

    def _base_url(self, env: str) -> str:
        default, _key_name, env_vars = self._environment(env)
        for env_var in env_vars:
            configured = _optional_config(env_var)
            if configured:
                return configured.rstrip("/")
        return default

    def _api_key(self, env: str) -> str:
        _base, key_name, _env_vars = self._environment(env)
        api_key = secret(key_name, "").strip()
        if not api_key:
            raise RuntimeError(f"{key_name} is required for Tavus env {env!r}.")
        return api_key

    def _build_url(
        self,
        path: str,
        *,
        env: str,
        params: dict[str, Any] | None,
    ) -> str:
        raw_path = (path or "").strip()
        if not raw_path:
            raise RuntimeError("path is required.")

        parsed = urlparse(raw_path)
        if parsed.scheme or parsed.netloc:
            if parsed.scheme != "https" or parsed.netloc not in _ALLOWED_HOSTS:
                raise RuntimeError(
                    "Only Tavus public API URLs on tavusapi.com/test.rqh/stg.rqh are allowed."
                )
            url = httpx.URL(raw_path)
        else:
            path_part = raw_path.lstrip("/")
            if path_part.startswith("api/v2/"):
                path_part = path_part.removeprefix("api/v2/")
            if path_part == "api/v2":
                path_part = ""
            if path_part.startswith("v2/"):
                path_part = path_part.removeprefix("v2/")
            if path_part == "v2":
                path_part = ""
            url = httpx.URL(f"{self._base_url(env).rstrip('/')}/{path_part}")

        if params:
            url = url.copy_merge_params(
                {key: str(value) for key, value in params.items() if value is not None}
            )
        return str(url)

    def _request(
        self,
        path: str,
        *,
        env: str = "prod",
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any] | str:
        url = self._build_url(path, env=env, params=params)
        response = self._client.get(
            url,
            headers={"accept": "application/json", "x-api-key": self._api_key(env)},
        )
        if response.status_code == 401:
            raise RuntimeError(f"Tavus API auth failed for env {env!r}.")
        if response.status_code == 403:
            raise RuntimeError(f"Tavus API key for env {env!r} lacks access.")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text[:1000]
            raise RuntimeError(
                f"Tavus API error {response.status_code} for env {env!r}: {body}"
            ) from exc
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return response.text

    def get(
        self,
        path: str,
        env: str = "prod",
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any] | str:
        """Read a Tavus public API path with GET.

        Use env="prod" for https://tavusapi.com/v2, env="staging" or
        env="test" for https://test.rqh.tavusapi.com/v2, and env="stg" for the
        formal stg RQH surface.
        """
        return self._request(path, env=env, params=params)

    def get_persona(self, persona_id: str, env: str = "prod") -> dict[str, Any] | list[Any] | str:
        """Fetch one persona by persona_id."""
        return self._request(f"personas/{persona_id}", env=env)

    def list_personas(
        self,
        env: str = "prod",
        limit: int = 20,
    ) -> dict[str, Any] | list[Any] | str:
        """List personas in the selected Tavus environment."""
        return self._request("personas", env=env, params={"limit": max(1, min(limit, 100))})

    def get_conversation(
        self,
        conversation_id: str,
        env: str = "prod",
        verbose: bool = True,
    ) -> dict[str, Any] | list[Any] | str:
        """Fetch one conversation by conversation_id."""
        params = {"verbose": str(verbose).lower()} if verbose else None
        return self._request(f"conversations/{conversation_id}", env=env, params=params)

    def list_conversations(
        self,
        env: str = "prod",
        persona_id: str | None = None,
        replica_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any] | list[Any] | str:
        """List conversations, optionally filtered by persona, replica, or status."""
        return self._request(
            "conversations",
            env=env,
            params={
                "persona_id": persona_id,
                "replica_id": replica_id,
                "status": status,
                "limit": max(1, min(limit, 100)),
            },
        )

    def ready(self, env: str = "prod") -> dict[str, Any]:
        """Probe Tavus API auth for an environment without returning customer data."""
        try:
            self._request("personas", env=env, params={"limit": 1})
        except Exception as exc:
            return {"ok": False, "env": env, "error": str(exc)}
        return {"ok": True, "env": env, "base_url": self._base_url(env)}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> TavusApiClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _client() -> TavusApiClient:
    return TavusApiClient()
