from __future__ import annotations

import sys
import types

import pytest

if "centaur_sdk" not in sys.modules:
    sdk_module = types.ModuleType("centaur_sdk")
    sdk_module.secret = lambda name, default="": default  # type: ignore[attr-defined]
    sys.modules["centaur_sdk"] = sdk_module

from . import client as client_module
from .client import SignozClient


def test_headers_preserve_broker_placeholders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "secret", lambda name, default="": name)

    headers = SignozClient()._headers()

    assert headers["SIGNOZ-API-KEY"] == "SIGNOZ_API_KEY"
    assert headers["X-SigNoz-URL"] == "SIGNOZ_URL"
