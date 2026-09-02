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
  - docs/ci/codex-assesment.md
  - _bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-08-31/ARCHITECTURE-SPINE.md
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

## CI/CD Requirements Addendum

The following requirements extend FR11 and NFR3–NFR5 for the recovered CI/CD initiative.
The stable identifiers are defined in the CI/CD architecture spine and are included here for
story traceability.

- CI-AR1–CI-AR6: one active GitHub-or-Gitea forge, portable/action-first workflows, and a
  three-adapter/one-verifier topology.
- CI-AR7–CI-AR12: a `just` local interface, one committed version authority, guarded SemVer
  release transaction, exact stable-tag agreement, and next-patch `.devN` identities.
- CI-AR13–CI-AR18: one wheel/sdist set, exact-wheel image provenance, precise build evidence,
  Epic 8 multi-platform publication, immutable identities, and verify-before-mutation.
- CI-AR19–CI-AR21, CI-AR24–CI-AR25, CI-AR28–CI-AR29, and CI-AR31: active destination,
  privilege, Release, forward-only alias, and retention requirements.
- CI-AR22, CI-AR23, CI-AR26, CI-AR27, and CI-AR30: retired historical requirements preserved
  only on `archive/publication-transaction-v1` at the recorded archive commit.
- CI-AR32–CI-AR35: secret-free pull requests, safe local `act`, isolated pinned Gitea runners,
  and an evidence-backed Gitea migration gate.
- CI-AR36–CI-AR41: boundary revalidation, destination-local failure, maintained-action recovery,
  one-build image fan-out, required-job/credential isolation, and workflow-native run evidence.

### CI/CD Coverage Map

| Requirement group | Primary stories |
|---|---|
| CI-AR1–CI-AR6 | 7.3, 7.5, 8.1, 8.2, 9.1, 9.2 |
| CI-AR7–CI-AR12 | 7.1, 7.2, 8.1, 8.2 |
| CI-AR13–CI-AR18 | 7.3, 7.4, 7.5, 8.1, 8.2 |
| CI-AR19–CI-AR21 | 8.1, 8.2 |
| CI-AR22, CI-AR23, CI-AR26, CI-AR27, CI-AR30 | retired; archive branch only |
| CI-AR24–CI-AR25 | 8.1, 8.2, 9.1 |
| CI-AR28–CI-AR29 | 8.3, 9.2 |
| CI-AR31 | 7.4, 8.4, 9.2 |
| CI-AR32–CI-AR35 | 7.5, 9.1, 9.2 |
| CI-AR36–CI-AR37 | 8.1, 8.2, 8.3 |
| CI-AR38 | 8.1, 8.2, 8.4, 9.2 |
| CI-AR39–CI-AR40 | 8.1, 8.2, 8.3, 9.2 |
| CI-AR41 | 8.1, 8.2, 8.3, 8.4, 9.2 |

## Epic 7: Reproducible Build and Verification

Maintainers and contributors can run one reproducible, secret-free build and verification
process locally, on pull requests, on GitHub, and on Gitea, producing a package/image evidence
bundle suitable for later publication.

**Dependencies:** none (Epics 1–6 are already archived).

### Story 7.1: Establish the Reproducible Local Package and Image Workflow

As a maintainer,
I want a discoverable `just` interface over the project's existing Poetry, test, Docker, and
workflow tools,
So that local work uses the same entry points and artifact contracts as CI.

**Acceptance Criteria:**

**Given** a supported development machine with `just`, Poetry, Python, Git, and Docker
**When** `just --list` is run
**Then** documented recipes exist for `setup`, `lint`, `test`, `test-local`, `package`, `image`,
`build`, `verify`, and `release PART` (CI-AR7)

**Given** `just package` is invoked from the repository root or a subdirectory
**When** it completes
**Then** Poetry builds exactly one wheel and one sdist into a clean output directory
**And** package metadata and wheel installation are validated

**Given** `just image` or `just build` is invoked
**When** the image is built
**Then** the image installs the wheel created by the package recipe rather than rebuilding the
project or resolving an independent dependency set (CI-AR13, CI-AR14)

**Given** a developer invokes `just verify`
**When** the recipe graph is evaluated
**Then** lint, tests, package validation, clean-environment installation, image build, and smoke
checks execute through named recipes and stop at the first failure

**Technical Acceptance Criteria:**

- The `justfile` is a thin command graph; project-specific parsing or state changes live in
  tested Python modules or composite actions rather than multi-page shell recipes.
- Recipe parameters are safely quoted and `set shell` enables fail-fast behavior without
  printing secrets.
- Package output cleanup is limited to a repository-owned explicit artifact directory.
- The image build accepts the wheel path and expected SHA-256 as inputs and fails when either
  differs from the recorded package artifact.
- Unit/contract tests prove recipe presence and that `build`/`verify` reach both package and
  image verification without a publish command.
- Developer documentation identifies required tools, supported versions, and the difference
  between secret-free local verification and protected publication.

### Story 7.2: Execute a Guarded Semantic Release Transaction

As a maintainer,
I want `just release major|minor|patch` to perform a guarded, atomic release transaction,
So that the application version, release commit, repository tag, and later publications cannot
drift.

**Acceptance Criteria:**

**Given** a release part other than `major`, `minor`, or `patch`
**When** the recipe validates input
**Then** it fails before changing a file or contacting the remote (CI-AR9)

**Given** the worktree is dirty, `HEAD` is detached, the current branch is not the configured
default branch, or local/upstream history differs
**When** release preflight runs
**Then** it fails with an actionable diagnostic and makes no version, commit, tag, or push change

**Given** all preconditions and verification pass
**When** `just release patch` runs from version `1.2.3`
**Then** it changes the single committed authority to `1.2.4`, keeps the lock consistent,
creates commit `release: v1.2.4`, creates annotated tag `v1.2.4`, and atomically pushes the
branch and exact tag (CI-AR8–CI-AR10)

**Given** the target tag exists locally or remotely
**When** preflight resolves the target
**Then** it fails without force-moving, deleting, or overwriting any tag

**Technical Acceptance Criteria:**

- A tested release-transaction module owns SemVer calculation, Git state validation, committed
  version updates, target-tag checks, and construction of the explicit `git push --atomic`
  command.
- Subprocess arguments are arrays, not shell-interpolated strings; external values are never
  evaluated as code.
- The transaction re-reads committed and built metadata after the bump and before commit/tag.
- A push failure reports the recoverable local commit/tag and exact next steps; it does not
  attempt destructive rollback or a non-atomic fallback.
- Unit tests cover all bump types, `0.x` versions, dirty/detached/diverged state, existing tags,
  failed verification, failed commit/tag, and atomic-push failure.
- Workflow contract tests prove stable CI is triggered by the exact tag and contains no code
  that chooses or bumps the stable version.

### Story 7.3: Define Build Evidence and Run Secret-Free Quality Verification

As a pipeline maintainer,
I want version and build-manifest contracts plus a reusable secret-free verifier,
So that every adapter agrees on immutable build inputs, outputs, error handling, and evidence.

**Acceptance Criteria:**

**Given** a workflow requests verification
**When** it calls `verify-build.yaml`
**Then** the only semantic inputs are channel, package version, and source SHA
**And** the workflow requests no publisher secret, OIDC write permission, or package-write
permission (CI-AR5, CI-AR18, CI-AR32)

**Given** the source, tag, and committed metadata disagree
**When** version validation runs
**Then** the verifier fails before building or uploading an artifact (CI-AR11)

**Given** a build manifest is created or consumed
**When** its composite action validates it
**Then** it conforms to the checked-in versioned JSON schema, rejects unknown unsafe fields,
and contains no secret value, secret length, or secret-derived hash (CI-AR15, CI-AR36)

**Technical Acceptance Criteria:**

- A checked-in JSON schema defines strict, versioned `build-manifest-v1` without credentials.
- A single committed-version reader serves local and CI callers and validates Poetry metadata,
  package metadata, and strict `vMAJOR.MINOR.PATCH` tags.
- Reusable workflow outputs expose only artifact names and non-sensitive identifiers.
- Errors name the failed contract field and destination but never print tokens or secret-derived
  diagnostics.
- Unit tests cover schema-valid examples, unknown fields, malformed hashes/digests, invalid
  channels/tags/toggles, and redaction guarantees.
- Workflow tests parse every YAML file and prove job-level least privilege, secret-free verifier
  calls, and no publisher job can run without the verifier in its transitive `needs` graph.

### Story 7.4: Build and Prove One Native-Verified Artifact Set

As a release maintainer,
I want one verified wheel/sdist set and a native image smoke result from the exact wheel,
So that later publishers receive artifacts proven to originate from the same source.

**Acceptance Criteria:**

**Given** verification runs for a source SHA and planned package version
**When** package build completes
**Then** it produces exactly one wheel and one sdist, records their SHA-256 hashes, installs the
wheel in an empty environment, and proves the CLI reports the planned version (CI-AR13)

**Given** the package evidence is valid
**When** the verifier's image build runs
**Then** it performs native image smoke from the exact verified wheel (CI-AR14, CI-AR18)
**And** multi-platform OCI publication and descriptor inspection remain Epic 8 work (CI-AR16)

**Given** container smoke tests inspect either platform
**When** the installed Python distribution is queried
**Then** its version and wheel identity match the build manifest

**Given** any required test or hash check fails
**When** verification concludes
**Then** no promotable artifact is emitted and no publication adapter can run

**Technical Acceptance Criteria:**

- The verifier checks out the requested full SHA with persisted Git credentials disabled.
- Build outputs have an explicit directory layout and 30-day artifact retention (CI-AR31).
- `build-manifest.json` uses schema/version identifier `build-manifest-v1` and records only source
  SHA, package version, optional development distance, filenames/hashes, image inputs/labels, and
  their fingerprint; channel, platforms, lock hash, and observed digest are not manifest fields.
- BuildKit cache is performance-only; cache hits cannot bypass hash, platform, package-install,
  or smoke validation.
- Tests inject a changed wheel, missing sdist, wrong source SHA, and wrong installed version and
  require hard failures; Epic 8 tests enforce the two-platform published index.
- Any provenance/SBOM output references the same manifest digest and is evidence, not an
  alternate identity source.

### Story 7.5: Integrate Pull Requests, Local Act, and Workflow Governance

As a contributor,
I want pull requests and local `act` runs to execute the same verification graph safely,
So that issues are found before merge without exposing credentials or modifying my worktree.

**Acceptance Criteria:**

**Given** a pull request, including one from a fork
**When** `ci.yaml` executes
**Then** it calls the reusable verifier with read-only contents permission and no secrets,
OIDC permission, login, push, release, or alias job (CI-AR2, CI-AR32)

**Given** `just test-local workflow=ci` is run from a dirty worktree
**When** `act` checks out or cleans its workspace
**Then** it operates on a disposable clone/worktree and the developer's branch, index, tracked
changes, and untracked files remain byte-for-byte unchanged (CI-AR33)

**Given** workflow files are changed
**When** repository validation runs
**Then** `actionlint`, pre-commit, and workflow contract tests pass and no step branches on
`ACT`

**Given** the cutover is complete
**When** `.github/workflows` is enumerated
**Then** only `ci.yaml`, `dev.yaml`, `release.yaml`, and `verify-build.yaml` implement this
pipeline (CI-AR5)

**Technical Acceptance Criteria:**

- `ci.yaml` has explicit pull-request triggers, workflow-level `contents: read`, cancellable
  ref-scoped concurrency, and a job-level reusable-workflow call.
- The local `act` recipe validates its workflow selector against an allowlist and uses a
  temporary location created safely by the operating system.
- Cleanup is scoped to that disposable location, runs on success/failure/signal, and never
  uses the repository root or an unresolved variable as a destructive target.
- Sample local `.act` variable/secret files contain synthetic placeholders and are ignored;
  production tokens are explicitly rejected/documented.
- Dependabot covers GitHub Actions and Poetry dependencies. Approved first-party and
  LiquidLogicLabs actions use documented major aliases; other exceptions are reviewed and
  recorded (CI-AR3, CI-AR4).
- Contract tests prove trigger exclusivity: PR owns verification, main push owns development,
  and exact stable tag owns stable publication.

## Epic 8: Action-Based Multi-Channel Delivery

Maintainers can publish verified development and stable packages and images through ordinary
destination jobs, then advance mutable aliases only after the required jobs succeed.

**Dependencies:** Epic 7.

### Story 8.1: Publish Immutable Development Packages and Images

As a maintainer,
I want default-branch artifacts published from the verified bundle,
So that development delivery creates immutable identities without rebuilding.

**Acceptance Criteria:**

**Given** a push to the protected default branch
**When** `dev.yaml` runs
**Then** it fails closed on an unknown forge, fetches full history/tags once, derives the
next-patch `.devN` version, suppresses dev publication when the source has an exact stable tag,
and calls `verify-build.yaml` once
**And** each required or enabled publisher downloads and validates `SHA256SUMS` and
`build-manifest.json` before login or upload (CI-AR36)

**Given** the active forge and optional external destinations
**When** development publishers run
**Then** the forge image is required, the Gitea package index is required when hosted on Gitea,
TestPyPI and Docker Hub obey strict booleans, and each credential is job-scoped

**Given** image publication runs
**When** the immutable `dev-<12sha>` image is published
**Then** one Buildx multi-platform invocation consumes the exact wheel and applies tags for the
required forge registry plus optional Docker Hub, with no per-registry rebuild
**And** digest/platform inspection is emitted as workflow outputs and run summary (CI-AR39,
CI-AR41)

**Technical Acceptance Criteria:**

- Use approved maintained actions for artifact download, registry login, metadata, and image
  publication. Package upload uses
  `pypa/gh-action-pypi-publish@<reviewed-full-commit-sha>` and implementation records the reviewed
  actual SHA (CI-AR3, CI-AR38).
- Publish the exact wheel/sdist and exact-wheel image inputs recorded by the verifier; no
  publisher rebuilds the Python package (CI-AR13–CI-AR18).
- Derive every forge coordinate from `github.server_url` and `github.repository` alone, failing
  closed on an unrecognised forge (`FORGE_REGISTRY` is retired). The image job gets only enabled
  image credentials; package credentials stay isolated.
- Workflow contract tests prove guards, strict toggles, secret isolation, one image invocation,
  and two-platform inspection. Story 8.3 alone owns the `dev` alias finalizer.
- Full criteria live in
  `_bmad-output/implementation-artifacts/epic-008/sprint-01/stories/E008-S01-001.md`.

### Story 8.2: Publish Stable Packages and Images from Exact Tags

As a release maintainer,
I want an exact deliberate tag to publish the verified stable distributions and images,
So that PyPI, the active forge, and optional Docker Hub receive one version identity.

**Acceptance Criteria:**

**Given** an exact `vX.Y.Z` tag
**When** `release.yaml` starts
**Then** it fails closed on an unknown forge and requires an annotated tag whose peeled commit is
the event SHA and reachable from the protected default branch
**And** tag, Poetry metadata, lock, built package, application version, and source SHA agree before
publisher jobs receive credentials

**Given** the verified stable bundle
**When** publisher jobs run
**Then** PyPI obeys `PUBLISH_PACKAGE_PYPI`, the active forge image is required, the Gitea package
index is required on Gitea, and Docker Hub obeys `PUBLISH_IMAGE_DOCKERHUB`

**Given** an invalid toggle, tag mismatch, checksum failure, manifest failure, or publisher error
**When** the workflow evaluates the run
**Then** it fails clearly and no alias-finalization job runs

**Technical Acceptance Criteria:**

- The reviewed-full-SHA package action and the one image job consume only the verifier artifact
  with job-scoped permissions/credentials (CI-AR24, CI-AR36, CI-AR38–CI-AR40).
- One Buildx invocation publishes both `linux/amd64` and `linux/arm64` under exact immutable tags
  for every enabled registry and records digest/platform outputs (CI-AR39, CI-AR41).
- Workflow tests prove exact-tag ownership, channel routing, and absence of any CI version bump.
- Full criteria live in
  `_bmad-output/implementation-artifacts/epic-008/sprint-01/stories/E008-S01-002.md`.

### Story 8.3: Create the Forge Release and Finalize All Aliases Last

As a release maintainer,
I want the forge Release and every development/stable alias finalized after publication,
So that human-facing records and convenient tags never lead the immutable artifacts.

**Acceptance Criteria:**

**Given** all required stable publishers succeeded
**When** the release job runs
**Then** it creates the exact-tag forge Release and attaches wheel, sdist, `SHA256SUMS`, and
`build-manifest.json`

**Given** the forge Release succeeds
**When** finalization runs
**Then** approved actions move Git aliases `vX`/`vX.Y` and digest-copy operations move image
aliases `X`/`X.Y`/`latest`
**And** prereleases or failed/skipped required jobs never move stable aliases

**Given** all required development publishers succeeded
**When** `dev` finalization becomes eligible
**Then** workflow concurrency has prevented an obsolete finalizer and a just-in-time fetch proves
the candidate remains the protected default-branch head
**And** a stale candidate leaves `dev` unchanged

**Technical Acceptance Criteria:**

- Release and alias jobs have only the permissions they need and are the only CI jobs allowed to
  write repository Release/ref state (CI-AR24, CI-AR28–CI-AR29, CI-AR40).
- Image aliases copy the published manifest by digest rather than rebuilding it.
- Stable aliases are forward-only; Story 8.3 is the sole owner of both dev and stable finalizers.
- Workflow outputs/summaries retain Release URL, digest/platforms, head check, and alias outcomes
  (CI-AR41).
- Full criteria live in
  `_bmad-output/implementation-artifacts/epic-008/sprint-01/stories/E008-S01-003.md`.

### Story 8.4: Cut Over the Workflow Topology and Document Failed-Jobs-Only Recovery

As an operator,
I want one production workflow topology and a failed-jobs-only recovery procedure,
So that old publishers cannot race the new paths and recovery is understandable.

**Acceptance Criteria:**

**Given** development and stable staging runs are green
**When** cutover completes
**Then** `ci.yaml`, `dev.yaml`, `release.yaml`, and `verify-build.yaml` are the only pipeline
workflows and their triggers are mutually owned

**Given** a destination job fails after another destination succeeds
**When** an operator follows the runbook
**Then** only failed jobs rerun against retained verifier evidence, successful immutable package
uploads are not repeated, and aliases remain blocked until success

**Given** failed-jobs-only rerun is unsupported, evidence expired, or immutable identity conflicts
**When** recovery is evaluated
**Then** the run halts and escalates, using a new development version where appropriate
**And** whole-workflow rerun, overwrite, force update, and deletion are never normal recovery

**Technical Acceptance Criteria:**

- The runbook documents exact GitHub and supported Gitea failed-jobs-only operations and covers
  invalid toggles, missing credentials, service failure, immutable conflicts, expiry, alias
  failure, and escalation (CI-AR38).
- Workflow/test evidence is retained for 30 days (CI-AR31).
- Run correlation is workflow-native output/summary evidence, not a new schema (CI-AR41).
- Contract tests prove there are no dangling local workflow/action references after cutover.
- Full criteria live in
  `_bmad-output/implementation-artifacts/epic-008/sprint-01/stories/E008-S01-004.md`.

## Epic 9: Practical Gitea Certification

Operators can certify the shared workflows on one pinned, isolated, private-CA-capable Gitea
runner tuple before moving repository ownership.

**Dependencies:** Epic 8.

### Story 9.1: Pin Gitea Runners, Bootstrap Trust, and Isolate Credentials

As a Gitea operator,
I want a pinned runner baseline with explicit bootstrap/downstream trust and scoped credentials,
So that the shared workflows have a secure, reproducible host environment.

**Acceptance Criteria:**

**Given** the supported Gitea environment
**When** its support matrix is inspected
**Then** server, act-runner, runner image, action majors, artifact protocol exceptions, and
upgrade/recertification rules are pinned

**Given** untrusted verification and protected publication
**When** runner labels and mounts are inspected
**Then** they use separate pools, ephemeral workspaces, and no shared publisher credentials

**Given** private-CA Gitea
**When** a runner is provisioned
**Then** runner-host bootstrap trust exists before registration, forge/action resolution, or job
startup; a first job step never claims to establish trust needed to start itself

**Given** a running job contacts a downstream private-CA endpoint
**When** job-level trust is needed
**Then** the approved CA import action installs that separate downstream trust before the request
**And** each scoped credential reaches only its own package, image, or Release job

**Technical Acceptance Criteria:**

- Document bootstrap versus downstream CA, minimal scopes, labels, network access, cache isolation,
  rotation, and rollback (CI-AR24, CI-AR25, CI-AR34).
- Unknown forges fail closed; coordinates are derived from action context alone, with no
  operator-supplied registry value (`FORGE_REGISTRY` is retired).
- A smoke workflow proves checkout, artifacts, Poetry, QEMU/Buildx, CA trust, and cleanup without
  publishing.
- Full criteria live in
  `_bmad-output/implementation-artifacts/epic-009/sprint-01/stories/E009-S01-001.md`.

### Story 9.2: Certify Gitea Staging and Gate Migration

As an operator,
I want a focused staging checklist and migration runbook,
So that ownership moves only after the exact production workflow graph is proven.

**Acceptance Criteria:**

**Given** the pinned Gitea staging tuple
**When** certification runs
**Then** it proves fork-safe PR verification, dev and stable package/image destinations,
private CA boundaries, artifacts, the one-build two-platform image flow, forge Release,
forward-only aliases, and one failed-jobs-only rerun

**Given** the pinned Gitea tuple cannot rerun only failed jobs
**When** recovery certification is evaluated
**Then** certification fails and migration remains blocked rather than accepting a whole-workflow
rerun that repeats successful immutable package uploads

**Given** certification is green
**When** the migration checklist runs
**Then** owners validate variables/secrets, disable the old owner, move the repository, run one
shadow verification, enable production publication, and retain a tested rollback point

**Technical Acceptance Criteria:**

- Evidence records the pinned tuple, workflow/run IDs, source/tag, build-manifest/checksum hashes,
  image digest/platforms, Release URL, alias job conclusion, and cleanup result without secrets.
- A negative suite proves untrusted code cannot select protected runners, obtain credentials, or
  mutate a package, image, Release, or alias, and a stale dev candidate cannot move `dev`
  (CI-AR29, CI-AR32–CI-AR35, CI-AR38–CI-AR41).
- Certification expires when any pinned tuple component changes.
- Full criteria live in
  `_bmad-output/implementation-artifacts/epic-009/sprint-01/stories/E009-S01-002.md`.
