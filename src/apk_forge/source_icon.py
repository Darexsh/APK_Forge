from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

ICON_NAMES = ("icon.png", "icon.webp", "icon.jpg", "icon.jpeg")
IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}


def extract_source_icon(source_package: Path, app_id: str, output_dir: Path) -> Path | None:
    """Extract a package sidecar icon or its declared Android launcher icon."""
    try:
        with zipfile.ZipFile(source_package) as package:
            sidecar = _find_sidecar_icon(package)
            if sidecar is not None:
                return _write_icon(package.read(sidecar), Path(sidecar).suffix, app_id, output_dir)

            if source_package.suffix.lower() == ".apk":
                return _extract_apk_icon(source_package, app_id, output_dir)

            apk_members = sorted(
                (name for name in package.namelist() if name.lower().endswith(".apk")),
                key=lambda name: (Path(name).name.lower() != "base.apk", name.count("/"), name),
            )
            for member in apk_members:
                with tempfile.TemporaryDirectory(prefix="apk-forge-icon-") as temp_dir:
                    nested_apk = Path(temp_dir) / "source.apk"
                    nested_apk.write_bytes(package.read(member))
                    icon_path = _extract_apk_icon(nested_apk, app_id, output_dir)
                    if icon_path is not None:
                        return icon_path
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    return None


def _find_sidecar_icon(package: zipfile.ZipFile) -> str | None:
    candidates = [
        name for name in package.namelist()
        if "/" not in name and name.lower() in ICON_NAMES
    ]
    return sorted(candidates, key=lambda name: ICON_NAMES.index(name.lower()))[0] if candidates else None


def _extract_apk_icon(apk_path: Path, app_id: str, output_dir: Path) -> Path | None:
    aapt = _find_aapt()
    if aapt is None:
        return None
    try:
        badging = _run_aapt(aapt, "dump", "badging", str(apk_path))
        icon_match = re.search(r"\bicon='([^']+)'", badging or "")
        if icon_match is not None:
            icon_resource = icon_match.group(1)
            if Path(icon_resource).suffix.lower() in IMAGE_SUFFIXES:
                image = _read_apk_image(apk_path, icon_resource, app_id, output_dir)
                if image is not None:
                    return image

            # Prefer a packaged density-specific launcher bitmap when present. It
            # includes the adaptive background and avoids rebuilding the layers.
            launcher_bitmap = _extract_named_icon_resource(aapt, apk_path, app_id, output_dir)
            if launcher_bitmap is not None:
                return launcher_bitmap

            # Adaptive launcher icons point to a foreground resource. Prefer that
            # recognizable artwork over a density-specific full-size icon.
            xmltree = _run_aapt(aapt, "dump", "xmltree", str(apk_path), icon_resource)
            foreground = re.search(
                r"E: foreground\b(?:(?!\n\s*E: ).)*?A: [^\n]*\(0x01010199\)=@0x([0-9a-fA-F]+)",
                xmltree or "",
                re.DOTALL,
            )
            if foreground is not None:
                icon = _extract_resource_id_icon(
                    aapt, apk_path, foreground.group(1), app_id, output_dir
                )
                if icon is not None:
                    return icon

        # Some apps expose the same launcher art under another named drawable,
        # and some split packages omit the launcher resource from the base APK.
        fallback = _extract_named_icon_resource(
            aapt, apk_path, app_id, output_dir, splash_only=badging is None
        )
        if fallback is not None:
            return fallback
    except (OSError, zipfile.BadZipFile, subprocess.SubprocessError):
        return None
    return None


def _extract_resource_id_icon(
    aapt: str, apk_path: Path, resource_id: str, app_id: str, output_dir: Path
) -> Path | None:
    resources = _run_aapt(aapt, "dump", "--values", "resources", str(apk_path))
    if resources is None:
        return None
    pattern = re.compile(
        rf"resource 0x{resource_id.lower().zfill(8)}\b[^\n]*\n\s*\(string8\) \"([^\"]+)\""
    )
    try:
        with zipfile.ZipFile(apk_path) as apk:
            archive_names = set(apk.namelist())
            for match in pattern.finditer(resources):
                resource_name = match.group(1)
                for image_path in _resource_archive_candidates(resource_name):
                    if image_path not in archive_names:
                        continue
                    image_data = apk.read(image_path)
                    image_suffix = _image_suffix(image_data, image_path)
                    if image_suffix is not None:
                        return _write_icon(image_data, image_suffix, app_id, output_dir)
                    if image_path.lower().endswith(".xml"):
                        rendered = _render_vector_icon(aapt, apk_path, image_path, app_id, output_dir)
                        if rendered is not None:
                            return rendered
    except (OSError, zipfile.BadZipFile):
        return None
    return None


def _extract_named_icon_resource(
    aapt: str, apk_path: Path, app_id: str, output_dir: Path, *, splash_only: bool = False
) -> Path | None:
    resources = _run_aapt(aapt, "dump", "--values", "resources", str(apk_path))
    if resources is None:
        return None
    terms = [term for term in re.split(r"[-_]+", app_id.lower()) if len(term) > 2]
    if app_id.lower() == "protonvpn":
        terms.append("vpn")
    elif app_id.lower() == "protonmail":
        terms.append("mail")
    candidates = []
    pattern = re.compile(
        r"resource 0x[0-9a-fA-F]+\s+[^\s]+:(?:drawable|mipmap)/([^:\s]+):[^\n]*\n\s*\(string8\) \"([^\"]+)\""
    )
    for match in pattern.finditer(resources):
        name, path = match.groups()
        lowered = name.lower()
        if splash_only or not (
            "launcher" in lowered or "logo" in lowered or any(term in lowered for term in terms)
        ):
            continue
        score = (
            (name in {"ic_launcher", "launcher"}) * 100
            + (name in {"ic_launcher_round", "launcher_round"}) * 90
            + sum(term in lowered for term in terms) * 10
            + ("launcher" in lowered) * 3
            + ("logo" in lowered)
        )
        if Path(path).suffix.lower() in IMAGE_SUFFIXES:
            score += 20
        candidates.append((score, path))
    # Split archives can have a valid app logo while their base APK has a dangling
    # icon reference. The conventional splash-logo resource is the intended fallback.
    splash_candidates = [(100, match.group(1)) for match in re.finditer(
            r'\(string8\) "([^"]*logosplash\.(?:png|webp|jpe?g))"', resources, re.IGNORECASE
        )]
    candidates.extend(splash_candidates)
    candidates.sort(reverse=True)
    try:
        with zipfile.ZipFile(apk_path) as apk:
            for _, path in candidates:
                if path not in apk.namelist():
                    continue
                data = apk.read(path)
                suffix = _image_suffix(data, path)
                if suffix:
                    return _write_icon(data, suffix, app_id, output_dir)
                if path.lower().endswith(".xml"):
                    rendered = _render_vector_icon(aapt, apk_path, path, app_id, output_dir)
                    if rendered:
                        return rendered
    except (OSError, zipfile.BadZipFile):
        return None
    return None


def _render_vector_icon(aapt: str, apk_path: Path, xml_member: str, app_id: str, output_dir: Path) -> Path | None:
    try:
        tree = _run_aapt(aapt, "dump", "xmltree", str(apk_path), xml_member)
        if tree is None:
            return None
        if "E: animated-vector " in tree:
            target = re.search(r"E: animated-vector\b(?:(?!\n\s*E: ).)*?\(0x01010199\)=@0x([0-9a-fA-F]+)", tree, re.DOTALL)
            if target is None:
                return None
            resources = _run_aapt(aapt, "dump", "--values", "resources", str(apk_path))
            if resources is None:
                return None
            resource_pattern = re.compile(
                rf"resource 0x{target.group(1).lower().zfill(8)}\b[^\n]*\n\s*\(string8\) \"([^\"]+)\""
            )
            for candidate in resource_pattern.finditer(resources):
                path = candidate.group(1)
                if path.lower().endswith(".xml"):
                    rendered = _render_vector_icon(aapt, apk_path, path, app_id, output_dir)
                    if rendered is not None:
                        return rendered
            return None
        if "E: vector " not in tree:
            return None
        viewport_width = _vector_float(tree, "viewportWidth")
        viewport_height = _vector_float(tree, "viewportHeight")
        if not viewport_width or not viewport_height:
            return None
        paths = []
        definitions = []
        path_pattern = re.compile(r"E: path\b(?P<attrs>.*?)(?=\n\s*E: |\Z)", re.DOTALL)
        for match in path_pattern.finditer(tree):
            attrs = match.group("attrs")
            data_match = re.search(r'android:pathData\([^\n]*?\)="([^"]*)"', attrs)
            if data_match is None:
                continue
            fill_match = re.search(r"android:fillColor\([^\n]*?\)=([^\n]+)", attrs)
            fill_value = fill_match.group(1) if fill_match else "#00000000"
            fill = _vector_color(fill_value)
            fill_resource = re.search(r"@0x([0-9a-fA-F]+)", fill_value)
            if fill_resource is not None:
                gradient = _vector_gradient(aapt, apk_path, fill_resource.group(1), len(definitions))
                if gradient is not None:
                    gradient_id, gradient_svg = gradient
                    definitions.append(gradient_svg)
                    fill = f"url(#{gradient_id})"
            if fill == "#00000000":
                continue
            stroke_match = re.search(r"android:strokeColor\([^\n]*?\)=([^\n]+)", attrs)
            stroke = _vector_color(stroke_match.group(1)) if stroke_match else "none"
            width_match = re.search(r"android:strokeWidth\([^\n]*?\)=\(type 0x4\)0x([0-9a-fA-F]+)", attrs)
            stroke_width = _decode_aapt_float(width_match.group(1)) if width_match else 0
            fill_alpha = _vector_float(attrs, "fillAlpha", default=1.0)
            paths.append(
                f'<path d="{data_match.group(1)}" fill="{fill}" fill-opacity="{fill_alpha}" '
                f'stroke="{stroke}" stroke-width="{stroke_width}" />'
            )
        if not paths:
            return None
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" '
            f'viewBox="0 0 {viewport_width} {viewport_height}"><defs>'
            + "".join(definitions) + "</defs>" + "".join(paths) + "</svg>"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{app_id}-icon.png"
        try:
            import cairosvg

            cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(output_path))
        except ImportError:
            converter = shutil.which("magick") or shutil.which("convert")
            if converter is None:
                return None
            command = [converter, "-", str(output_path)] if Path(converter).name == "magick" else [converter, "svg:-", str(output_path)]
            result = subprocess.run(command, input=svg, text=True, capture_output=True, check=False)
            if result.returncode != 0 or not output_path.is_file():
                return None
        from PIL import Image

        with Image.open(output_path) as rendered_image:
            if rendered_image.convert("RGBA").getchannel("A").getbbox() is None:
                output_path.unlink(missing_ok=True)
                return None
        return output_path
    except (OSError, ValueError, struct.error, subprocess.SubprocessError, ImportError):
        return None


def _vector_float(tree: str, attribute: str, default: float = 0.0) -> float:
    match = re.search(rf"android:{attribute}\([^\n]*?\)=\(type 0x4\)0x([0-9a-fA-F]+)", tree)
    return _decode_aapt_float(match.group(1)) if match else default


def _decode_aapt_float(value: str) -> float:
    return struct.unpack(">f", int(value, 16).to_bytes(4, "big"))[0]


def _vector_color(value: str) -> str:
    value = value.strip()
    if "@0x" in value:
        return "#00000000"
    color = re.search(r"0x([0-9a-fA-F]{8})", value)
    if color:
        argb = color.group(1)
        return f"#{argb[2:]}" if argb[:2].lower() == "ff" else f"#{argb[2:]}{argb[:2]}"
    return value if value.startswith("#") else "#00000000"


def _vector_gradient(aapt: str, apk_path: Path, resource_id: str, suffix: int) -> tuple[str, str] | None:
    resources = _run_aapt(aapt, "dump", "--values", "resources", str(apk_path))
    if resources is None:
        return None
    pattern = re.compile(
        rf"resource 0x{resource_id.lower().zfill(8)}\b[^\n]*\n\s*\(string8\) \"([^\"]+\.xml)\""
    )
    match = pattern.search(resources)
    if match is None:
        return None
    tree = _run_aapt(aapt, "dump", "xmltree", str(apk_path), match.group(1))
    if tree is None or "E: gradient " not in tree:
        return None
    gradient_match = re.search(r"E: gradient\b(?P<attrs>.*?)(?=\n\s*E: item|\n\s*E: |\Z)", tree, re.DOTALL)
    attrs = gradient_match.group("attrs") if gradient_match else ""
    angle = _attribute_float(attrs, "angle")
    start_x, start_y = _attribute_float(attrs, "startX"), _attribute_float(attrs, "startY")
    end_x, end_y = _attribute_float(attrs, "endX"), _attribute_float(attrs, "endY")
    stops = []
    for item in re.finditer(r"E: item\b(?P<attrs>.*?)(?=\n\s*E: |\Z)", tree, re.DOTALL):
        item_attrs = item.group("attrs")
        color = re.search(r"android:color\([^\n]*?\)=\(type 0x1c\)0x([0-9a-fA-F]{8})", item_attrs)
        offset = re.search(r"android:offset\([^\n]*?\)=\(type 0x4\)0x([0-9a-fA-F]+)", item_attrs)
        if color and offset:
            color_value = _vector_color("0x" + color.group(1))
            offset_value = _decode_aapt_float(offset.group(1))
            stops.append(f'<stop offset="{offset_value}" stop-color="{color_value[:7]}" stop-opacity="{int(color.group(1)[:2], 16) / 255}"/>')
    if not stops:
        return None
    gradient_id = f"g{suffix}"
    gradient_svg = (
        f'<linearGradient id="{gradient_id}" gradientUnits="userSpaceOnUse" x1="{start_x}" y1="{start_y}" '
        f'x2="{end_x}" y2="{end_y}">' + "".join(stops) + "</linearGradient>"
    )
    return gradient_id, gradient_svg


def _attribute_float(attrs: str, attribute: str) -> float:
    match = re.search(rf"android:{attribute}\([^\n]*?\)=\(type 0x4\)0x([0-9a-fA-F]+)", attrs)
    return _decode_aapt_float(match.group(1)) if match else 0.0


def _read_apk_image(apk_path: Path, member: str, app_id: str, output_dir: Path) -> Path | None:
    try:
        with zipfile.ZipFile(apk_path) as apk:
            if member in apk.namelist():
                return _write_icon(apk.read(member), Path(member).suffix, app_id, output_dir)
    except (OSError, zipfile.BadZipFile):
        pass
    return None


def _write_icon(data: bytes, suffix: str, app_id: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{app_id}-icon{suffix.lower()}"
    output_path.write_bytes(data)
    return output_path


def _resource_archive_candidates(resource_name: str) -> tuple[str, ...]:
    path = Path(resource_name)
    names = [resource_name]
    if path.suffix:
        names.extend((f"res/{resource_name}",))
    else:
        names.extend(f"{prefix}{resource_name}{suffix}" for prefix in ("", "res/") for suffix in (".png", ".webp", ".jpg", ".jpeg"))
    return tuple(names)


def _image_suffix(data: bytes, archive_name: str) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    suffix = Path(archive_name).suffix.lower()
    return suffix if suffix in IMAGE_SUFFIXES else None


def _find_aapt() -> str | None:
    executable = "aapt.exe" if os.name == "nt" else "aapt"
    on_path = shutil.which(executable)
    if on_path:
        return on_path
    roots = [os.environ.get("ANDROID_SDK_ROOT"), os.environ.get("ANDROID_HOME")]
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            roots.append(str(Path(local_app_data) / "Android" / "Sdk"))
        roots.append(str(Path.home() / "AppData" / "Local" / "Android" / "Sdk"))
    else:
        roots.extend(("/opt/android-sdk", "/usr/local/lib/android/sdk"))
    seen_roots: set[str] = set()
    for root in filter(None, roots):
        normalized_root = os.path.normcase(os.path.abspath(root))
        if normalized_root in seen_roots:
            continue
        seen_roots.add(normalized_root)
        build_tools = Path(root) / "build-tools"
        if build_tools.is_dir():
            candidates = sorted(build_tools.glob(f"*/{executable}"), reverse=True)
            if candidates:
                return str(candidates[0])
    return None


def _run_aapt(aapt: str, *args: str) -> str | None:
    result = subprocess.run(
        [aapt, *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout if result.returncode == 0 else None
