* * *

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&height=220&text=APK%20Forge&fontAlign=50&fontAlignY=50&color=0:263238,50:455A64,100:00ACC1&fontColor=ffffff" width="100%" /><br>
<a href="https://git.io/typing-svg"><img src="https://readme-typing-svg.demolab.com/?lines=Private+APK+catalog+automation;Patch%2C+sign%2C+publish%2C+and+track+APK+builds;Vault-backed+source+packages+and+release+assets;Incremental+syncs+with+clear+failure+reports;Built+for+controlled+personal+Android+workflows&center=true&width=820&color=00ACC1&pause=1000" alt="Typing SVG" /></a>

![Status](https://img.shields.io/badge/Status-Active-brightgreen)
![Python](https://img.shields.io/badge/Python-3.11-blue)
![Platform](https://img.shields.io/badge/Platform-GitHub%20Actions-24292f?logo=github)
![Scope](https://img.shields.io/badge/Scope-Public%20Engine-orange)
![License](https://img.shields.io/badge/License-GPLv3-blue)
![Scheduler](https://img.shields.io/badge/Scheduler-cron--job.org-00ACC1?logo=clockify&logoColor=white)

</div>

* * *

## ✨ Author

| Name | GitHub | Role | Focus |
| --- | --- | --- | --- |
| **[Darexsh by Daniel Sichler](https://github.com/Darexsh)** | [Repositories](https://github.com/Darexsh?tab=repositories) | Automation, Android tooling, CI/CD | Private APK catalog automation, build orchestration, release workflow |

* * *

## 🚀 Overview

**APK Forge** is a public automation engine for building a private Android APK catalog from owner-supplied source packages and patch definitions.

The repository intentionally contains only the reusable engine: CLI code, schemas, tests, and GitHub Actions workflow logic. Real app choices, source packages, signing material, release assets, generated catalog output, and tokens belong in a separate private **Vault** repository.

Forge does not scrape APK mirror websites. Source packages are supplied and controlled by the vault owner.

### Why APK Forge exists

* Keep private app state out of the public engine repository.
* Build patched APKs from known source packages.
* Publish source and patched APKs through private release assets.
* Rebuild only when something meaningful changed.
* Continue building other apps when one app fails.
* Send clean failure summaries while keeping detailed logs in Actions.

* * *

## 🧱 Architecture

```text
public engine repository
  APK Forge CLI
  schemas
  tests
  GitHub Actions workflow

private vault repository
  apps.json
  catalog.json
  source packages
  signing key
  release note templates

private release assets
  source-apks
  patched-apks
  archive-apks
```

`apps.json` describes what should be built.  
`catalog.json` describes what was actually built, published, and installable.

See [VAULT.md](VAULT.md) for the expected private repository layout.


---

## ⏰ Automated Scheduling

APK Forge uses [cron-job.org](https://cron-job.org/) as an external scheduler for the `Sync Vault` GitHub Actions workflow.

Instead of relying on GitHub Actions' native `schedule` event, cron-job.org sends an authenticated HTTP request to the GitHub REST API. GitHub Actions then executes the complete synchronization pipeline.

### Schedule

| Setting | Configuration |
| --- | --- |
| Scheduler | [cron-job.org](https://cron-job.org/) |
| Frequency | Daily |
| Execution time | 07:00 |
| Timezone | `Europe/Berlin` |
| Trigger | GitHub REST API (`workflow_dispatch`) |
| Workflow | `.github/workflows/sync-vault.yml` |
| Default mode | Incremental sync (`force: false`) |

The `Europe/Berlin` timezone automatically accounts for daylight saving time.

### Execution Flow

1. cron-job.org sends a scheduled POST request to the GitHub Actions workflow dispatch endpoint.
2. GitHub authenticates the request using a dedicated fine-grained personal access token.
3. The `Sync Vault` workflow is triggered with `force: false`.
4. APK Forge checks the private vault configuration and synchronizes changed apps.
5. Updated APKs and catalog changes are published to the private vault.
6. GitHub Actions retains execution logs, and Telegram sends failure notifications when configured.

### Manual Execution

The workflow can also be started manually from the [GitHub Actions page](https://github.com/Darexsh/APK_Forge/actions/workflows/sync-vault.yml).

Manual execution supports the `force` input:

- `false` (default): Only rebuild apps when relevant inputs or release assets have changed.
- `true`: Force rebuilding and republishing even when the catalog and releases appear unchanged.

### Authentication & Reliability

cron-job.org uses a dedicated fine-grained GitHub personal access token with **Actions: Read and write** permission limited to the `APK_Forge` repository.

External scheduling avoids GitHub Actions' native cron trigger limitations, but actual workflow startup still depends on GitHub runner availability.

A successful HTTP `204 No Content` response confirms that GitHub accepted the workflow dispatch request, not that the synchronization completed successfully.

The scheduler token must be renewed before expiration to keep automatic synchronization running.

* * *

## ✨ Feature Highlights

### Source Package Control

* Supports owner-supplied source packages from local vault folders or private GitHub release assets.
* Supports `.apk`, `.apkm`, `.apks`, and `.xapk` source packages.
* Converts bundle-style source packages into patch-ready APKs when needed.
* Stores SHA-256 hashes in the private app configuration.

### Build Pipeline

* Downloads required tools automatically into the workspace.
* Applies patch bundles per app.
* Streams live build progress and patch output into GitHub Actions logs.
* Signs and verifies final APKs.
* Publishes signed APKs to a private patched release.

### Incremental Sync

Forge skips unchanged apps by comparing:

* source app version name
* source app version code
* expected patched asset
* current patch bundle identity
* enabled patch overrides
* disabled patch overrides
* existing release assets

Changing only one app's patch selection rebuilds only that app.

### Failure Handling

* One failed app does not stop the full sync.
* Successful apps are still published.
* The workflow exits failed if any app failed.
* Telegram alerts can send one clean summary for all failed apps.
* Full patch logs remain available in GitHub Actions.

* * *

## ⚙️ Local Workflow

Run commands from this repository with `PYTHONPATH=src` during local development.

PowerShell:

```powershell
$env:PYTHONPATH="src"
```

Bash:

```bash
export PYTHONPATH=src
```

### 1. Validate the private config

```bash
python -m apk_forge validate --config /path/to/vault/apps.json
```

### 2. Preview the build plan

```bash
python -m apk_forge plan \
  --config /path/to/vault/apps.json \
  --vault-root /path/to/vault \
  --workspace-root /path/to/vault/tmp
```

### 3. Publish source packages

```bash
python -m apk_forge source publish \
  --all \
  --config /path/to/vault/apps.json \
  --vault-root /path/to/vault \
  --repo owner/private-vault \
  --body-template /path/to/vault/docs/source-apks-release.md
```

### 4. Run the full sync

```bash
python -m apk_forge sync \
  --config /path/to/vault/apps.json \
  --vault-root /path/to/vault \
  --workspace-root /path/to/vault/tmp \
  --catalog /path/to/vault/catalog.json \
  --repo owner/private-vault \
  --body-template /path/to/vault/docs/patched-apks-release.md
```

* * *

## 🧩 Patch Selection

Per-app patch overrides live in the private `apps.json`.

```json
"patches": {
  "enable": [
    "Patch name"
  ],
  "disable": [
    "Broken patch name"
  ]
}
```

Patch selection is part of the build fingerprint. If you change it, Forge rebuilds that app on the next sync.

* * *

## 🔐 Secrets

The `Sync Vault` workflow uses repository secrets instead of hardcoded private values.

| Secret | Purpose |
| --- | --- |
| `VAULT_REPO` | Private vault repository, for example `owner/private-vault` |
| `VAULT_DIR` | Vault checkout directory inside the workflow workspace |
| `VAULT_TOKEN` | Fine-grained token with vault contents read/write and metadata read |
| `TELEGRAM_BOT_TOKEN` | Optional Telegram bot token for failure alerts |
| `TELEGRAM_CHAT_ID` | Optional Telegram chat id for failure alerts |

The workflow keeps running details in GitHub Actions and sends only the final failure summary to Telegram.

* * *

## 🧰 Useful Commands

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

Validate a generated catalog:

```bash
python -m apk_forge catalog validate --catalog /path/to/vault/catalog.json
```

Print the SHA-256 digest for a source package:

```bash
python -m apk_forge hash /path/to/source.apk
```

* * *

## 🧪 Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

* * *

## 📁 Project Files

| Path | Purpose |
| --- | --- |
| `src/apk_forge/` | Engine source code |
| `tests/` | Unit tests |
| `schemas/` | JSON schemas for app config and catalog files |
| `.github/workflows/` | CI/CD workflow |
| `VAULT.md` | Private vault setup reference |

* * *

## 📜 License

APK Forge is licensed under the **GNU General Public License v3.0**.

See [LICENSE](LICENSE) for the full license text.

* * *

## ⚠️ Disclaimer & Legal

APK Forge is the automation layer only. This public repository does not provide apps, APK downloads, source APKs, patched APKs, media assets, or private catalog data.

* **Engine only:** The code here describes how a vault-backed build pipeline can validate, patch, sign, publish, and catalog Android packages. It does not contain the packages themselves.
* **Private inputs:** Source packages, signing material, app selections, generated catalogs, and release assets are expected to live outside this public repository.
* **No endorsement:** APK Forge is not affiliated with patch tool maintainers, compatibility-layer projects, Google, app publishers, patch authors, or any third-party service that may be referenced by a private vault configuration.
* **Operator responsibility:** Whoever uses this engine is responsible for their own vault contents, source package rights, patch choices, release visibility, and compliance with applicable licenses and terms.
* **No guarantees:** Automated builds can fail, patch behavior can change, and generated APKs may behave differently from their original sources. Review outputs before trusting or installing them.
* **Runtime dependencies:** Some non-root patched apps may require a compatible service-layer installation, depending on the selected patches and app.

* * *

<div align="center"><sub>Created with ❤️ by Daniel Sichler</sub></div>
