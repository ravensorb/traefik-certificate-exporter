---
stepsCompleted: [1, 2, 3, 4]
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md
  - docs/architecture.md
  - docs/guidelines.md
  - docs/adr/0001-python-dependency-management-poetry.md
  - docs/adr/0002-container-base-image-and-privilege-model.md
  - docs/adr/0003-logging-stack-and-secret-redaction.md
  - docs/adr/0004-dependency-build-artifact-parity.md
  - docs/adr/0005-ci-reusable-workflow-wiring.md
---

# traefik-certificate-exporter - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for
traefik-certificate-exporter, decomposing the requirements from the PRD and Architecture
(no UX design contract — this is a headless CLI/Docker tool with no UI) into implementable
stories.

No starter template applies — this is an existing, shipped project (v0.1.3), not a
greenfield build.

## Requirements Inventory

### Functional Requirements

FR1: Parse both legacy (v1, `DomainsCertificate.Certs`) and current (v2, `Certificates`) Traefik ACME JSON shapes.
FR2: Export each domain's private key, leaf cert, chain, full chain, and a PKCS12 (`.pfx`) bundle.
FR3: Support both a "flat" layout and a per-domain subfolder layout for exported files.
FR4: Filter which domains are exported via an include-list or an exclude-list (mutually exclusive).
FR5: Optionally scope processing to one named Traefik certificate resolver, or auto-detect resolver nodes in the JSON.
FR6: Run once at start and/or watch the data path continuously for file create/modify events.
FR7: Debounce rapid repeated filesystem events for the same file (coalesce into one export pass).
FR8: Optionally restart Docker containers labeled with the exported domain name, to pick up the new cert.
FR9: Support a dry-run mode that logs intended actions without writing files or restarting containers.
FR10: Configurable via CLI flags, a YAML config file, or environment variables (CLI > env var > config file > packaged default).
FR11: Ship as a PyPI package and as a Docker image (linuxserver.io-style, s6-overlay, PUID/PGID).

### NonFunctional Requirements

NFR1: Must not leak certificate private keys or PKCS12 passphrases into logs, at any log level.
NFR2: Must reliably signal misconfiguration (e.g. missing data path) rather than silently continuing.
NFR3: Installable via `pip install traefik-certificate-exporter` with no missing transitive imports.
NFR4: CI must build and publish the package/image on every tagged release.
NFR5: Regressions in ACME parsing (v1/v2) or export logic must be caught before release (automated tests).
NFR6: Logs should be structured/traceable enough to diagnose a failed export after the fact.
NFR7: First container boot should produce a usable default config without manual intervention.

### Additional Requirements

From `docs/architecture.md` and its recorded ADRs:

- Docker image's installed dependency set must be built from the locked `poetry.lock` set, never a separately hand-maintained package list (ADR-0004).
- Retain the linuxserver.io base image + PUID/PGID privilege-drop model; the base image must be pinned by digest and kept on a currently-supported release (ADR-0002).
- File-handler log output must be structured (JSON) with secrets redacted at every log level; no cross-boundary correlation ID is required (single-process tool, nothing to correlate across) (ADR-0003).
- `build.yaml` must invoke `build-package.yaml`/`build-container.yaml` as job-level reusable workflows (`uses:` at the job level), not step-level references to a nonexistent custom-actions path (ADR-0005).
- Dependency/environment management stays on Poetry (already established); no migration to `uv` without a newly recorded ADR (ADR-0001).

From `docs/guidelines.md` (project-specific engineering guidelines):

- The CI pipeline must behave identically under GitHub Actions, Gitea Actions, and local `nektos/act` — no step may branch on the `ACT` environment variable, under any circumstances (§7).
- Prefer well-maintained marketplace GitHub Actions over hand-rolled shell; the "LiquidLogicLabs" vendor preference is now confirmed (org: `github.com/LiquidLogicLabs`) — see guidelines §6 for the resolved preference and which actions apply to open findings.
- Public-repo governance files are required: `SECURITY.md` (private vulnerability disclosure — this project handles private keys/passphrases), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue templates, a PR template; GitHub's repo-level secret-scanning/push-protection must be confirmed enabled (§9).
- Pre-commit hooks are already wired (`ruff`, `gitleaks`, `actionlint`, `pre-commit-hooks`) and must stay green — new work should not introduce violations these hooks would catch (§10).
- Config validation rules must be enforced identically across all three input surfaces (CLI, config file, env var) — a rule enforced only at the CLI layer (e.g. today's domain include/exclude mutual exclusivity) is a defect (§5).

Testing (ties FR/NFR to a concrete deliverable):

- An automated `pytest` suite is required covering ACME v1/v2 parsing, `Settings` loading, and `DockerManager` restart logic, wired into CI (NFR5).
- Any test fixtures (sample certs/domains) must be synthetic, never real captured data.

### UX Design Requirements

N/A — no UI; this is a headless CLI/Docker tool.

### FR Coverage Map

FR1: Epic 1 - ACME v1/v2 parsing, protected by regression tests
FR2: Epic 1 - multi-format export (PEM + PFX), protected by regression tests
FR3: Epic 1 - flat/per-domain layout modes, protected by regression tests
FR4: Epic 3 - domain include/exclude, made consistent across CLI/config/env
FR5: Epic 1 - resolver scoping, protected by regression tests
FR6: Epic 1 - run-once/watch modes, protected by regression tests
FR7: Epic 1 - event debounce, protected by regression tests
FR8: Epic 1 - Docker container restart, protected by regression tests
FR9: Epic 1 - dry-run mode, protected by regression tests
FR10: Epic 3 - CLI/config-file/env-var precedence, made consistent
FR11: Epic 2 - PyPI + Docker distribution, made reliable end-to-end
NFR1: Epic 1 - no secret leakage in logs
NFR2: Epic 1 - loud failure on misconfiguration
NFR3: Epic 2 - no missing transitive dependencies
NFR4: Epic 2 - CI reliably builds/publishes on release
NFR5: Epic 1 - automated regression test suite
NFR6: Epic 4 - structured, diagnosable logs
NFR7: Epic 4 - working first-run Docker config

## Epic List

### Epic 1: Trustworthy Certificate Export Core
Users can trust that every certificate this tool exports is correct, that a misconfiguration
fails loudly instead of silently, and that secrets are never exposed in logs — and future
changes can't silently regress any of this because the whole export surface is now covered
by automated tests.
**FRs covered:** FR1, FR2, FR3, FR5, FR6, FR7, FR8, FR9 (hardened via regression tests) · **NFRs:** NFR1, NFR2, NFR5

### Epic 2: Reliable Installation, Build & Release Pipeline
Users can install this tool via `pip` or Docker and get a working, consistent result every
time, and maintainers can trust that tagging a release actually builds and publishes it —
consolidated into one epic because dependency declaration, the Docker image, and the CI
pipeline that builds both are the same tightly-coupled surface (touching `pyproject.toml`,
`docker/Dockerfile`, and `.github/workflows/*` together).
**FRs covered:** FR11 · **NFRs:** NFR3, NFR4

### Epic 3: Predictable, Documented Configuration
Users get identical, correct behavior no matter which of the three configuration surfaces
(CLI, config file, env var) they use, and every setting — including ones that exist in code
today but aren't documented — is discoverable.
**FRs covered:** FR4, FR10

### Epic 4: Smooth Docker Operator Experience
Users deploying the Docker image get a working configuration out of the box on first boot,
and can diagnose a failed export from structured log output rather than free-text guesswork.
**NFRs covered:** NFR6, NFR7

### Epic 5: Extended Integration Capability (Post-Export Hook)
Users who need to hand an exported certificate to another service — with different ownership,
permissions, or location — get a supported extension point instead of having to run a
separate sidecar/cron container to bridge the gap. New capability (not in the original FR
list; validated via GitHub issue #2, including the maintainer's own acknowledgment of the
gap). Fully standalone — does not require any other epic.

### Epic 6: Public Project Governance & Housekeeping
Prospective contributors and security researchers get clear, standard paths to contribute or
report a vulnerability responsibly (this project handles private keys and passphrases, which
raises the bar above a typical utility), and the repository's CI tooling stays current rather
than quietly rotting.
**Additional Requirements covered:** governance files, secret-scanning enablement, Action
version/vendor hygiene, dead-code removal (no FR/NFR numbers — these are hygiene/process
requirements from `docs/guidelines.md`, not product functionality).

**Recommended execution order:** 1 → 2 → 3 → 4 → 6 → 5. Epic 1's test suite is not a hard
dependency for the others, but every later epic benefits from it existing first. Epic 5 is
last since it is new, lowest-urgency scope with no dependents.

## Epic 1: Trustworthy Certificate Export Core

Users can trust that every certificate this tool exports is correct, that a misconfiguration
fails loudly instead of silently, and that secrets are never exposed in logs — and future
changes can't silently regress any of this because the whole export surface is now covered
by automated tests.

### Story 1.1: Redact Secrets from Debug Logs

As an operator running this tool with DEBUG logging enabled,
I want the PKCS12 passphrase and other secrets to never appear in logs,
So that enabling verbose logging for troubleshooting doesn't leak credentials into log files
or terminals.

**Acceptance Criteria:**

**Given** DEBUG logging is enabled and `pkcs12Passphrase` is set
**When** `SettingsManager._dump_settings()` or `_dump_config()` runs
**Then** the passphrase value never appears in plaintext in the output (e.g. rendered as `***REDACTED***`)
**And** the redaction mechanism is name/allowlist-based, so any future secret-shaped field added to `Settings` is redacted the same way without a code change per field

**Given** a secret field is `None` or absent
**When** the redaction step runs
**Then** it does not raise an exception

**Given** the redaction is implemented
**When** a unit test sets a known passphrase and triggers a debug dump
**Then** the test asserts the passphrase string never appears verbatim in the output (fulfills NFR1)

### Story 1.2: Fail Loudly on Missing or Invalid Data Path

As an operator who misconfigures or forgets to mount the data path,
I want the tool to fail loudly at startup,
So that I don't silently get zero certificate exports with no clear error.

**Acceptance Criteria:**

**Given** `--data-path`/config/env leave the data path unset
**When** the app starts
**Then** `Settings.dataPath` is `None` (not the literal string `"None"`)
**And** the app logs an ERROR and exits non-zero instead of proceeding to watch/export

**Given** a data path is set but does not exist on disk
**When** the app starts
**Then** the app logs an ERROR and exits non-zero

**Given** the same bug pattern exists for `outputPath`
**When** this fix is implemented
**Then** `outputPath` receives the identical fix in the same change (fulfills NFR2)

### Story 1.3: Automated Regression Tests for Certificate Export Core

As a maintainer,
I want regressions in ACME parsing, settings loading, and Docker restart logic caught before
release,
So that a change doesn't silently break certificate export for existing users.

**Acceptance Criteria:**

**Given** the existing ACME v1 (`DomainsCertificate.Certs`) and v2 (`Certificates`,
`lowercase`/`uppercase` key shapes) parsing logic in `AcmeCertificateExporter`
**When** the new `pytest` suite runs
**Then** each shape is exercised by at least one test using synthetic fixture data (fulfills
FR1, FR2, FR3, FR5)

**Given** `Settings`/`SettingsManager` loading precedence (CLI > env var > config file >
packaged default — env vars deliberately outrank the config file, matching this Docker-first
tool's deployment model) and the null-path fix from Story 1.2
**When** the test suite runs
**Then** each precedence layer and the null-path behavior are covered (fulfills FR6, FR7, FR9)

**Given** `DockerManager.restartLabeledContainers`
**When** the test suite runs with a mocked Docker client
**Then** label-matching logic is verified without requiring a real Docker daemon (fulfills FR8)

**Given** the suite is complete
**When** CI runs on a push or PR
**Then** a test failure fails the build (fulfills NFR5)

**And** all fixtures (sample ACME JSON, certs, keys, domains) are synthetic — never real
captured data

## Epic 2: Reliable Installation, Build & Release Pipeline

Users can install this tool via `pip` or Docker and get a working, consistent result every
time, and maintainers can trust that tagging a release actually builds and publishes it.

### Story 2.1: Declare the Missing Cryptography Dependency

As a user installing via `pip install traefik-certificate-exporter`,
I want every import the package needs to be guaranteed by its declared dependencies,
So that the install doesn't fail or behave inconsistently depending on what else happens to
already be present on the system.

**Acceptance Criteria:**

**Given** `cryptography` (`x509`, `hazmat.primitives`, `pkcs12`) is imported in
`certificate_exporter.py` and `scripts/dump-pkcs12.py` but absent from
`[tool.poetry.dependencies]`
**When** `cryptography` is added with an appropriate version constraint and `poetry.lock` is
regenerated
**Then** a clean environment with only declared dependencies installed can import the package
with no `ImportError` (fulfills NFR3)

### Story 2.2: Build the Docker Image from Locked Dependencies

As a maintainer,
I want the Docker image's installed dependencies to always match `pyproject.toml`/`poetry.lock`,
and `poetry` itself to not ship as a runtime dependency,
So that the package and the image can never silently disagree about what's installed.

**Acceptance Criteria:**

**Given** `poetry` is currently declared in `[tool.poetry.dependencies]` instead of the dev
group
**When** it is moved to `[tool.poetry.group.dev.dependencies]`
**Then** a built/published package's dependency tree no longer includes `poetry`

**Given** `docker/Dockerfile` hand-maintains an unpinned `pip install` list that has already
drifted (adds `pyOpenSSL`, not a declared project dependency)
**When** the image build is reworked into a multi-stage `poetry install --only main` build
stage per ADR-0004 (not `poetry export` — ruled out since it requires the separate
`poetry-plugin-export` plugin for no offsetting benefit)
**Then** the image's installed Python package set matches `poetry install`'s output exactly,
with no separate hand-written list remaining

### Story 2.3: Upgrade and Pin the Container Base Image

As a user running this in production,
I want the base image to be a currently-supported, security-patched release,
So that I'm not running on an EOL OS inside the container.

**Acceptance Criteria:**

**Given** `ghcr.io/linuxserver/baseimage-alpine:3.19` has been end-of-life for several months
(flagged in GitHub issue #6)
**When** the Dockerfile is updated to a currently-supported linuxserver.io Alpine base image
tag (verified against current linuxserver.io/Alpine release status, not assumed)
**Then** the image builds and existing functionality (cert export, container restart) still
works

**Given** the new base image tag is chosen
**When** the `FROM` line is finalized
**Then** it is pinned by digest (`@sha256:...`), per ADR-0002's follow-up

### Story 2.4: Repair the CI Release Pipeline Wiring

As a maintainer,
I want a push to `main`/`master` or a version tag to actually trigger the package and
container build/publish pipeline,
So that releases aren't silently broken.

**Acceptance Criteria:**

**Given** `build.yaml` calls `uses: ./.github/actions/build-package.yaml` /
`build-container.yaml` as steps at a path that doesn't exist
**When** it is rewritten per ADR-0005 to call both as job-level reusable workflows
(`uses: ./.github/workflows/...`, `secrets: inherit`, correct `needs:` ordering)
**Then** a push to `main`/`master` or a `v*` tag executes both the package and container
build/publish jobs (fulfills NFR4)

**Given** `actionlint` (wired via pre-commit) additionally flagged invalid config-variable
names, an unsupported `ubuntu-20.04` runner label, and a release job missing its `steps`
section
**When** those are fixed alongside the wiring repair
**Then** `actionlint` passes clean on `build.yaml`, `build-package.yaml`,
`build-container.yaml`, and `release.yaml`

### Story 2.5: Run CI Identically Across GitHub, Gitea, and Local Act

As a maintainer running the same workflow locally (via `act`), in Gitea Actions, and on real
GitHub Actions,
I want the pipeline to behave identically everywhere,
So that a workflow that passes locally doesn't fail — or behave differently — in real CI.

**Acceptance Criteria:**

**Given** `build-container.yaml` has a step gated `if: ${{ env.ACT }}` that installs a custom
CA certificate mounted via `act`'s `--container-options`
**When** it is replaced with a runner-agnostic mechanism (e.g. a custom runner image with the
CA baked in, verified against current `act`/Gitea Actions docs before choosing)
**Then** no step in `.github/workflows/` branches on the `ACT` environment variable

**Given** the replacement is in place
**When** `docker/act-build.sh` is run locally
**Then** it still succeeds

## Epic 3: Predictable, Documented Configuration

Users get identical, correct behavior no matter which of the three configuration surfaces
(CLI, config file, env var) they use, and every setting — including ones that exist in code
today but aren't documented — is discoverable.

### Story 3.1: Fix Domain Include/Exclude Across All Config Surfaces

As an operator setting `..._DOMAINS_INCLUDE` via environment variable or config file,
I want it to work on its own,
So that I don't have to also set `..._DOMAINS_EXCLUDE` to a dummy value just to avoid an
error (as reported in GitHub issue #5).

**Acceptance Criteria:**

**Given** only `..._SETTINGS_DOMAINS_INCLUDE` is set (env var or config file)
**When** the app starts and exports certificates
**Then** only the included domains are exported, with no error, and
`..._DOMAINS_EXCLUDE` does not need to be set

**Given** only `..._SETTINGS_DOMAINS_EXCLUDE` is set
**When** the app starts
**Then** the mirror case works with no error

**Given** both are set
**When** the app starts
**Then** it enforces mutual exclusivity with a clear error, consistently across CLI, config
file, and env var (matching, not diverging from, the CLI's existing `argparse`
mutually-exclusive-group behavior)

**Given** the fix lands
**When** `docker/README.md`'s `FIXME` comment describing the workaround is reviewed
**Then** it is removed, and GitHub issue #5 can be closed with a reference to the fix
(fulfills FR4)

### Story 3.2: Add and Document a PKCS12 Passphrase Setting

As an operator (raised in GitHub issue #3),
I want a documented, discoverable way to set the PKCS12 export passphrase,
So that I don't have to read the source code to find `pkcs12passphrase`.

**Acceptance Criteria:**

**Given** `Settings.pkcs12Passphrase` and the `pkcs12passphrase` config key already exist and
work via config file/env var, but there is no CLI flag and no documentation
**When** a `--pkcs12-passphrase` CLI flag is added, following existing `cli_args.py`
naming/dest conventions
**Then** the flag populates `Settings.pkcs12Passphrase` correctly

**Given** the setting now has three input surfaces
**When** `README.md`, `docker/README.md`, `config.sample.yml`, and `config_default.yaml` are
updated
**Then** all three (CLI flag, config key, `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_PKCS12PASSPHRASE`
env var) are documented consistently with how other settings are documented

**Given** Story 1.1's redaction fix exists
**When** the CLI-supplied passphrase is dumped via `_dump_config`/`_dump_settings`
**Then** it is redacted the same way (fulfills FR10; closes GitHub issue #3)

## Epic 4: Smooth Docker Operator Experience

Users deploying the Docker image get a working configuration out of the box on first boot,
and can diagnose a failed export from structured log output rather than free-text guesswork.

### Story 4.1: Seed a Working Config on First Container Boot

As an operator starting the container for the first time without a pre-existing config file,
I want a usable default `config.yaml` seeded automatically,
So that I don't have to know to manually copy the sample file in myself.

**Acceptance Criteria:**

**Given** the s6 init script checks `[ ! -f /config/config.yaml ]` but writes the sample to
`/config/config.yaml.sample` instead
**When** the `cp` destination is corrected
**Then** a fresh container start with an empty `/config` volume results in
`/config/config.yaml` existing as a usable copy of the sample

**Given** `/config/config.yaml` already exists
**When** the container boots
**Then** it is left untouched, with no overwrite of user edits (fulfills NFR7)

### Story 4.2: Emit Structured Logs for File Output

As a maintainer diagnosing a failed export from log files,
I want file logs to be structured (JSON) rather than free-text,
So that I can grep/parse them reliably without a bespoke regex per log line shape.

**Acceptance Criteria:**

**Given** all logging today is hand-formatted `"...".format(...)` strings with no JSON
formatter
**When** a JSON formatter is added to the file handlers in `logging.yaml`
**Then** each file log line is valid, parseable JSON with at minimum timestamp, level, logger
name, and message as separate keys

**Given** console output should remain human-readable
**When** the JSON formatter is added
**Then** console output (via `coloredlogs`) is unchanged

**Given** Story 1.1's secret redaction already applies
**When** the new JSON formatter is verified
**Then** redaction still holds — secrets do not leak through the new format (fulfills NFR6)

## Epic 5: Extended Integration Capability (Post-Export Hook)

Users who need to hand an exported certificate to another service — with different ownership,
permissions, or location — get a supported extension point instead of having to run a
separate sidecar/cron container to bridge the gap.

### Story 5.1: Support a Configurable Post-Export Command

As an operator (raised in GitHub issue #2) who needs to copy/chown/move an exported
certificate into another service's expected location with different ownership,
I want a supported way to run a custom command after export,
So that I don't have to run a separate scheduler container just to bridge file ownership
between this tool and another service.

**Acceptance Criteria:**

**Given** an optional `settings.postexportcommand` setting (following the existing
lowercase-dotted-key convention)
**When** it is set and an export pass completes successfully
**Then** the configured command runs via `subprocess.run` in list form (no `shell=True`),
with the comma-separated list of processed domain names exposed to it as the
`TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS` environment variable — following the
project's existing `TRAEFIK_CERTIFICATE_EXPORTER_` env-var naming convention

**Given** the command has not returned
**When** 30 seconds elapse (the fixed default timeout; not itself configurable in this
story — a `settings.postexportcommandtimeout` override is out of scope, see below)
**Then** the process is killed and the timeout is logged as an error, same as any other
command failure

**Given** the setting is unset (the default)
**When** an export pass completes
**Then** behavior is unchanged — this is purely additive

**Given** `settings.dryRun` is enabled
**When** an export pass would otherwise trigger the hook
**Then** the hook command is not executed, consistent with dry-run suppressing file writes
and container restarts

**Given** the hook command fails (non-zero exit) or times out
**When** this happens
**Then** it is logged as an error but does not crash the watch loop — the tool keeps
watching for the next change

**Given** the feature is implemented
**When** `README.md`/`docker/README.md` are updated and a unit test covers invocation
(including the exact env var name and comma-separated format), dry-run suppression, timeout,
and non-zero-exit failure handling with a mocked/fake command
**Then** GitHub issue #2 can be closed with a reference to the new capability

## Epic 6: Public Project Governance & Housekeeping

Prospective contributors and security researchers get clear, standard paths to contribute or
report a vulnerability responsibly, and the repository's CI tooling stays current rather than
quietly rotting.

### Story 6.1: Add Security Disclosure and Contribution Governance Files

As a prospective contributor or security researcher,
I want standard governance files (security disclosure process, contribution guidelines, code
of conduct, issue/PR templates) and platform-level secret scanning enabled,
So that I know how to contribute or report a vulnerability responsibly, and accidental
secrets are caught even if a local pre-commit hook is bypassed.

**Acceptance Criteria:**

**Given** no `SECURITY.md` exists today, despite this project handling private keys and PKCS12
passphrases
**When** `SECURITY.md` is added describing a private vulnerability-disclosure process
**Then** it is discoverable at the repo root

**Given** no `CONTRIBUTING.md` or `CODE_OF_CONDUCT.md` exist
**When** both are added
**Then** they are present at the repo root

**Given** no issue or PR templates exist
**When** `.github/ISSUE_TEMPLATE/` (bug report + feature request) and
`.github/PULL_REQUEST_TEMPLATE.md` are added
**Then** new issues/PRs on GitHub use them by default

**Given** GitHub's repository-level secret-scanning and push-protection settings
**When** they are checked
**Then** their enabled/disabled state is confirmed and recorded (this is a settings check, not
a file change — flag explicitly if repo-admin access isn't available in this context)

### Story 6.2: Align GitHub Actions Versions and Enable Dependabot

As a maintainer,
I want all GitHub Actions pinned to current, consistent major versions with Dependabot
keeping them current automatically,
So that the pipeline doesn't quietly rot on outdated action versions.

**Acceptance Criteria:**

**Given** `actions/checkout@v3`/`setup-python@v4` in `build-package.yaml` versus newer
versions elsewhere
**When** all actions across `.github/workflows/*.yaml` are checked against their current
marketplace listing and updated to a consistent major (or pinned to a commit SHA for
less-trusted third-party actions)
**Then** `actionlint` reports no stale-version findings

**Given** no `dependabot.yml` exists
**When** one is added covering the `github-actions` and Python ecosystems
**Then** dependency update PRs begin surfacing automatically

**Given** `docs/guidelines.md §6`'s "LiquidLogic actions" vendor preference was previously
unresolved
**When** this story is worked
**Then** the confirmed `LiquidLogicLabs` actions relevant to this repo's open findings
(`git-action-ca-certificate-import` for backlog item #11's ACT-conditional CA install,
`git-action-docker-act-compatibility` for `act`/GitHub Actions build-context parity) are
adopted in the affected workflows

### Story 6.3: Remove Dead Code and Disabled Tooling References

As a maintainer reading this codebase,
I want dead/commented-out code and disabled tool configs removed or replaced with a one-line
rationale,
So that the repo reflects what actually runs.

**Acceptance Criteria:**

**Given** commented-out code exists (the `sans` export loop in `certificate_exporter.py`,
disabled `poetry publish` steps in `build-package.yaml`, disabled `black`/`isort` hooks in
`.pre-commit-config.yaml` — superseded by `ruff`)
**When** each is reviewed
**Then** it is removed, or replaced with a one-line rationale comment if intentionally kept

**Given** `PemToPfxConverter.dump()` references an unimported `crypto` module and would raise
`NameError` if called
**When** it is confirmed unused (via `git grep`) and removed, or fixed if something does call
it
**Then** the method no longer contains dead/broken code

**Given** these are pure cleanup changes
**When** the Epic 1 test suite (Story 1.3) is run afterward
**Then** it still passes with no behavior change

