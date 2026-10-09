from __future__ import annotations

from apk_forge.models import PlannedApp


def format_plan(planned_apps: tuple[PlannedApp, ...]) -> str:
    lines = [f"Plan: {len(planned_apps)} enabled app(s)"]
    if not planned_apps:
        lines.append("No enabled apps to process.")
        return "\n".join(lines)

    for index, planned in enumerate(planned_apps, start=1):
        app = planned.app
        lines.extend(
            [
                "",
                f"{index}. {app.name} ({app.id})",
                f"   Package: {app.package_name}",
                f"   Source package: {planned.source_path}",
                f"   Source SHA-256: {planned.source_sha256}",
                f"   Patch-ready: {'yes' if planned.source_path.suffix.lower() == '.apk' else 'needs conversion'}",
                f"   MPP: {format_mpp_source(app.mpp)}",
                f"   Release prefix: {app.output.release_prefix}",
            ]
        )

        if app.output.asset_name is not None:
            lines.append(f"   Output asset: {app.output.asset_name}")
        if app.patches.enable:
            lines.append(f"   Enabled patches: {', '.join(app.patches.enable)}")
        if app.patches.disable:
            lines.append(f"   Disabled patches: {', '.join(app.patches.disable)}")

    return "\n".join(lines)


def format_mpp_source(mpp) -> str:
    if mpp.path is not None:
        return f"{mpp.owner}/{mpp.repository}:{mpp.path}@{mpp.ref}"
    asset = f":{mpp.asset}" if mpp.asset else ""
    return f"{mpp.owner}/{mpp.repository}@{mpp.release}{asset}"
