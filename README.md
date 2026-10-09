# APK Forge

APK Forge is an automation engine for building a private Android APK catalog
from owner-supplied source packages and patch definitions.

The public engine contains only generic code, schemas, tests, and workflows.
Real app choices, source packages, signing material, release assets, tokens,
and generated catalog output belong in a separate private vault repository.

See `VAULT.md` for the expected vault repository shape.

## Architecture

```text
public engine repository
  APK Forge CLI, schemas, tests, workflows

private vault repository
  apps.json, source packages, signing material, generated catalog

private GitHub releases
  source-apks, patched-apks
```

`apps.json` describes desired managed apps. `catalog.json` describes APKs that
actually exist and are installable.

## What Forge Does

- validates private `apps.json`
- resolves source packages from local private files or private GitHub release assets
- uploads owner-supplied source packages to a private `source-apks` release
- downloads the patching CLI and APKEditor when needed
- converts `.apkm`, `.apks`, and `.xapk` source packages into patchable APKs
- applies patch bundles
- signs and verifies patched APKs
- uploads signed APKs to a private `patched-apks` release
- updates private `catalog.json`
- skips unchanged apps during repeat sync runs

Forge intentionally does not scrape APK mirror websites. Source packages are
supplied by the vault owner.

## Quick Start

Run commands from this repository with `PYTHONPATH=src` during local development:

```bash
export PYTHONPATH=src
```

PowerShell:

```powershell
$env:PYTHONPATH="src"
```

Validate the private configuration:

```bash
python -m apk_forge validate --config /path/to/vault/apps.json
```

Preview planned work:

```bash
python -m apk_forge plan \
  --config /path/to/vault/apps.json \
  --vault-root /path/to/vault \
  --workspace-root /path/to/vault/tmp
```

Upload changed source packages and update `apps.json`:

```bash
python -m apk_forge source publish \
  --all \
  --config /path/to/vault/apps.json \
  --vault-root /path/to/vault \
  --repo owner/private-vault \
  --body-template /path/to/vault/docs/source-apks-release.md
```

Run the full local workflow:

```bash
python -m apk_forge sync \
  --config /path/to/vault/apps.json \
  --vault-root /path/to/vault \
  --workspace-root /path/to/vault/tmp \
  --catalog /path/to/vault/catalog.json \
  --repo owner/private-vault \
  --body-template /path/to/vault/docs/patched-apks-release.md
```

`sync` builds, signs, publishes, and updates the catalog. On later runs it skips
apps that already match the catalog and release asset state. Use `--force` to
rebuild and reupload unchanged apps.

## Useful Commands

Build and sign locally without publishing:

```bash
python -m apk_forge run \
  --config /path/to/vault/apps.json \
  --vault-root /path/to/vault \
  --workspace-root /path/to/vault/tmp \
  --execute
```

Build without signing:

```bash
python -m apk_forge run \
  --config /path/to/vault/apps.json \
  --vault-root /path/to/vault \
  --workspace-root /path/to/vault/tmp \
  --execute \
  --skip-signing
```

Publish already signed workspace APKs:

```bash
python -m apk_forge publish \
  --config /path/to/vault/apps.json \
  --vault-root /path/to/vault \
  --workspace-root /path/to/vault/tmp \
  --catalog /path/to/vault/catalog.json \
  --repo owner/private-vault \
  --body-template /path/to/vault/docs/patched-apks-release.md
```

Create an empty catalog:

```bash
python -m apk_forge catalog init --output /path/to/vault/catalog.json
```

Validate a catalog:

```bash
python -m apk_forge catalog validate --catalog /path/to/vault/catalog.json
```

Print the SHA-256 digest for a source package:

```bash
python -m apk_forge hash /path/to/source.apk
```

## Tokens And Signing

Forge reads `GITHUB_TOKEN` from the environment, local `.env`, or
`<vault-root>/.env`.

`apksigner` is detected from `PATH`, `ANDROID_HOME`, `ANDROID_SDK_ROOT`, or the
standard Windows Android SDK location. Override with `--apksigner`, `--keystore`,
`--key-alias`, `--keystore-password`, or `--key-password` when needed.

## Project Files

- `src/apk_forge/`: engine source
- `tests/`: unit tests
- `schemas/`: config and catalog schemas
- `VAULT.md`: private repository setup notes

## Test

```bash
PYTHONPATH=src python -m unittest discover -s tests
```
