# Engineering Standards — Docker Overlay

Loaded on top of `standards-core.md` when the project (or the component under review) ships a
container image.

## Base images — pinned by digest, minimal, and GA

**Rule.** Every `FROM` names a **GA tag AND a digest**: `FROM node:22-slim@sha256:…`. The tag
documents intent for a human; the digest is what actually builds.

- **Why both** — a tag alone resolves to whatever it points at that day, so the build is not
  reproducible and yesterday's green CI proves nothing about today's image. A digest alone is
  unreadable in review. Signatures, attestations and admission policies all bind to digests,
  so a policy that verifies by tag verifies nothing.
- **Minimal** — prefer slim, distroless or `scratch` for the final stage. Every package you
  do not ship is a CVE you do not triage.
- **GA only** — no `:latest`, no `:edge`, no release-candidate bases (core §8).
- **Review** — Flag: unpinned or `:latest` base, a digest with no accompanying tag, a
  full distro base where slim/distroless would serve. **BLOCKER** if the final stage carries a
  package manager, shell and build toolchain it does not need at runtime.

## Multi-stage — build tooling never reaches the final image

**Rule.** Compilers, dev dependencies, test fixtures and secrets stay in build stages.

- Order layers cheapest-to-change first (dependency manifests, then `install`, then source) so
  the dependency layer caches across source edits.
- Use BuildKit cache mounts (`--mount=type=cache`) for package caches rather than committing
  them to a layer.
- **Secrets** — `--mount=type=secret`, never `ARG`/`ENV` and never a `COPY`-then-`RM`. A
  deleted file is still in the layer beneath. **BLOCKER** on any credential in image history.

## Supply chain — SBOM and provenance at build time

**Rule.** CI builds emit both: `docker buildx build --sbom=true --provenance=true`.

- **Why at build time** — an SBOM scanned from a finished image cannot see what a multi-stage
  build discarded, and a distroless final stage defeats package-manager-based scanners
  entirely. Only the builder has each stage's resolved dependency graph.
- **Provenance answers what an SBOM cannot** — *where* an artifact was built, by what system,
  from which commit. An SBOM tells you what is inside; provenance tells you whether the thing
  that produced it was trustworthy.
- Scan images in CI (Trivy, Grype or Docker Scout) and fail on fixable HIGH/CRITICAL.

## Runtime posture

- **Non-root** — a numeric `USER`, not root, and not a name that may not resolve. Read-only
  root filesystem where the workload allows it.
- **`.dockerignore`** — exclude `.git`, secrets, local env files and build output. It protects
  both context size and against copying something you did not mean to ship.
- **Signals** — exec-form `ENTRYPOINT`/`CMD` (`["app"]`, not `app`) so PID 1 receives SIGTERM
  and the container stops rather than being killed.
- **Logs to stdout/stderr**, structured, with the correlation ID propagated (core §9). Never
  log to a file inside the container.
- **`HEALTHCHECK`** where the orchestrator does not already provide one.

## Review checklist (Docker-specific)

- [ ] Every `FROM` pinned by digest with a GA tag alongside it.
- [ ] Final stage minimal — no build toolchain, no package manager it does not need.
- [ ] No secret in any layer, `ARG`, `ENV` or in image history.
- [ ] `--sbom=true --provenance=true` in the CI build; image scanned, fixable HIGH/CRITICAL fail.
- [ ] Non-root numeric `USER`; read-only root FS where feasible.
- [ ] Exec-form entrypoint so signals reach the process.
- [ ] `.dockerignore` present and excludes VCS, secrets and build output.
- [ ] Structured logs to stdout with a propagated correlation ID (core §9).
