from __future__ import annotations

import tomllib
from pathlib import Path


def test_company_context_uses_cross_channel_public_history_reader() -> None:
    manifest_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    manifest = tomllib.loads(manifest_path.read_text())
    postgres_secret = manifest["tool"]["centaur"]["secrets"][0]

    assert postgres_secret["database"] == "ai_v2"
    assert postgres_secret["role"] == "centaur_company_context_reader"
    assert {
        setting["name"]: setting for setting in postgres_secret["settings"]
    } == {
        "centaur.slack_channel_id": {
            "name": "centaur.slack_channel_id",
            "value_from": {"principal_field": "slack_channel_id"},
        },
        "centaur.slack_team_id": {
            "name": "centaur.slack_team_id",
            "value_from": {"principal_field": "slack_team_id"},
        },
        "centaur.slack_user_id": {
            "name": "centaur.slack_user_id",
            "value_from": {"principal_field": "slack_user_id"},
        },
        "centaur.slack_history_channel_ids": {
            "name": "centaur.slack_history_channel_ids",
            "value_from": {"principal_field": "slack_history_channel_ids"},
        },
        "centaur.slack_include_public": {
            "name": "centaur.slack_include_public",
            "value": "true",
        },
    }
