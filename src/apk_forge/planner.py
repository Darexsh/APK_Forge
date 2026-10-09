from __future__ import annotations

from pathlib import Path

from apk_forge.models import AppsConfig, PlannedApp
from apk_forge.source_apk import plan_source_apk


def create_plan(
    config: AppsConfig,
    vault_root: Path,
    github_token: str | None = None,
    workspace_root: Path | None = None,
) -> tuple[PlannedApp, ...]:
    return tuple(
        plan_source_apk(app, vault_root, github_token, workspace_root)
        for app in config.enabled_apps
    )
