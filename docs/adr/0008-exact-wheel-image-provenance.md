# ADR-0008: Exact-wheel image provenance

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Maintainer (ravensorb), via Epic E007 Sprint S01
- **Principle(s) in tension:** Core §2 reuse over re-derivation, Core §3 enforce rules mechanically,
  Docker overlay (reproducible, minimal runtime image), supply-chain provenance
- **Amends:** ADR-0004 (Build the Docker image from the locked dependency set). ADR-0004's
  decision — the image's *dependency* set is derived from `poetry.lock` and never hand-maintained —
  remains in force and is still implemented. This ADR replaces only the mechanism by which the
  *application itself* enters the image.

## Context

ADR-0004 closed a real defect: the Dockerfile installed a hand-written, unpinned package list that
had already drifted from `pyproject.toml`. Its remedy was Poetry's documented Docker pattern —
`poetry install --only main --no-root --no-directory` for dependencies, then `COPY src/` followed by
`poetry install --only main` to install the application from the working tree.

That remedy makes the dependency set reproducible but leaves the *application* unaccounted for. Under
it, the image is built from a source tree, so the artifact that was tested (the wheel produced by
`poetry build` and validated by Twine) and the artifact that ships inside the image are two different
builds of the same source. They are expected to be equivalent; nothing checks that they are. The
project publishes both a Python package and a container image, and E007 required a single answer to
"what code is in this image, and is it the same code that passed verification?"

A second force is index access. Any image build that can reach a package index can, at a later
rebuild, resolve a *different* set of bytes for the same version string — through a yanked-and-
rereleased file, a mirror, or a compromised index. For an image that is supposed to be a faithful
container around one verified artifact, that is a provenance hole, not a convenience.

The shipped mechanism, in `docker/Dockerfile`, `docker-bake.hcl` and the `justfile`, resolves both:

- Dependencies still come from Poetry's manifest and lock alone (`docker/Dockerfile:29-32`) — ADR-0004
  unchanged.
- The application arrives as exactly one caller-supplied wheel, bind-mounted read-only from the build
  context (`docker/Dockerfile:38`) rather than copied, so a missing or ambiguous selection is
  reported by a validation step instead of failing inside `COPY` with an opaque cache-key error
  (`docker/Dockerfile:34-35`).
- Its SHA-256 is verified **inside** the build, against a caller-supplied `WHEEL_SHA256`, before the
  wheel is staged for installation (`docker/Dockerfile:58-69`).
- It is installed with `pip install --no-deps --no-index` (`docker/Dockerfile:87`) — no dependency
  resolution, no index, no fallback.
- `pip` is removed from the venv immediately afterwards (`docker/Dockerfile:95`), and only the
  populated venv crosses the stage boundary (`docker/Dockerfile:130`).

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Install the published package from a package index (`pip install traefik-certificate-exporter==$VERSION`) | Trivial Dockerfile; image build needs nothing but a version string; decouples image and package release cadence | Provenance is a version *string*, not bytes — a rebuild can legitimately produce a different image from identical inputs; the image cannot be built before the package is published, so a release cannot be verified end-to-end before it is public; requires network access to an index at build time | Fails the provenance goal outright |
| B. Build from source inside the image — ADR-0004's `COPY src/` + `poetry install --only main` | No prebuilt artifact needed; `docker build` works from a bare checkout; a security patch can be applied by rebuilding the image | The image contains a *second, unverified* build of the application; the wheel that Twine validated and the smoke tests exercised is not the artifact that ships; build tooling (Poetry, gcc, cargo, headers) must be present in the builder for the application step too | Satisfies dependency parity, not artifact identity |
| C. Bind-mount exactly one caller-supplied wheel, verify its SHA-256 in-build, install `--no-deps --no-index` | The image contains the exact bytes that were built, checked and smoke-tested once; provenance is a hash, not a name; no index is reachable, so no later substitution is possible; the caller (the `justfile` locally, the verifier in CI) supplies the same inputs by the same derivation | The image can no longer be built from a bare checkout; the wheel must exist first; a security patch has no in-image path and must go through a full rebuild of the wheel | Satisfies provenance and Core §3 (the rule is checked in-build, not documented) |

## Decision

**Option C — exact-wheel provenance.** One verified wheel is the single provenance root shared by
the published package and the image. The following are invariants, each enforced inside the build
rather than by convention.

1. **Exactly one wheel, named by the caller.** `WHEEL_PATH` must be non-empty, relative, and free of
   `..` (`docker/Dockerfile:40-45`); it must expand to exactly one existing file
   (`docker/Dockerfile:46-50`) whose name ends in `.whl` (`docker/Dockerfile:51-57`). Zero matches
   and multiple matches are both hard failures.

2. **The hash is checked before the wheel is used.** `WHEEL_SHA256` must be 64 lowercase hex
   characters (`docker/Dockerfile:58-61`), and the wheel's actual `sha256sum` must equal it
   (`docker/Dockerfile:62-66`). Only after that is the wheel staged into `/tmp/verified-wheel`
   (`docker/Dockerfile:67-69`), and the install step re-asserts that the staging directory holds
   exactly one wheel (`docker/Dockerfile:81-85`).

3. **No index, no resolver, for the application.** The install is
   `pip install --no-deps --no-index "${verified_wheel}"` (`docker/Dockerfile:87`). Dependencies come
   from `poetry install --only main --no-root --no-directory` against `pyproject.toml` and
   `poetry.lock` (`docker/Dockerfile:29-32`) — ADR-0004's decision, unchanged — and their mutual
   consistency with the wheel's declared requirements is checked by `pip check`
   (`docker/Dockerfile:94`). There is no path by which a same-version file fetched later could
   substitute for the artifact that was tested.

4. **The wheel's metadata is the version authority.** `VERSION` must be non-empty and must equal the
   version reported by `importlib.metadata` for the installed distribution
   (`docker/Dockerfile:88-93`), and `REVISION` must be a full lowercase source SHA
   (`docker/Dockerfile:76-79`). Both are stamped into the OCI labels
   `org.opencontainers.image.version` and `.revision` (`docker-bake.hcl:59-66`), so the shipped image
   carries the identity it was built from.

5. **`pip` does not ship.** It is materialised with `ensurepip` only for the install
   (`docker/Dockerfile:80`), then uninstalled (`docker/Dockerfile:95`), and only `/app/.venv` is
   copied into the runtime stage (`docker/Dockerfile:130`). Poetry, gcc, `musl-dev`, `libffi-dev`,
   `openssl-dev` and cargo stay in the builder.

6. **One derivation of the inputs, used by both callers.** `docker-bake.hcl` declares
   `WHEEL_PATH`, `WHEEL_SHA256`, `VERSION` and `REVISION` with empty defaults
   (`docker-bake.hcl:1-15`) and forwards them as build args (`docker-bake.hcl:50-57`), so a bare
   `docker buildx bake image` fails closed on invariant 1 rather than building something
   unintended. Locally, `just image` declares `build` as a prerequisite so the wheel is always
   rebuilt and validated first, then derives the path, the SHA-256, the version from the wheel's own
   `METADATA`, and the revision from `git rev-parse HEAD` (`justfile:36-57`). In CI, the verifier
   derives the same four values from the revalidated build manifest before invoking the same Bake
   target (`.github/workflows/verify-build.yaml:461-493`).

7. **Fail closed, always.** A missing wheel, several wheels, a non-`.whl` selection, a malformed or
   mismatched SHA-256, a malformed revision, and a wheel whose metadata version disagrees with
   `VERSION` are each a build failure with a distinct message. None of them degrade to a warning or
   to a fallback path.

## Consequences

- Positive: the image's application bytes are, by hash, the bytes that `poetry build` produced,
  `twine check` validated, and the wheel and sdist smoke tests exercised. "Same version" is replaced
  by "same file".
- Positive: one artifact, one provenance root. The wheel published to the index and the wheel inside
  the image are not two builds that ought to agree; they are one file.
- Positive: the build has no application package-index dependency at all, so an index outage,
  a yanked file, or a compromised mirror cannot change what a rebuild produces.
- Positive: the final image contains neither `pip` nor a build toolchain, shrinking the runtime
  attack surface beyond what ADR-0004 achieved.
- Negative / trade-off accepted: **the image can no longer be built from a bare checkout.** A wheel
  must exist first. `just image` handles this by depending on `just build` (`justfile:36`, `:43`),
  but any other caller — a direct `docker build`, an unprepared CI job, a downstream consumer
  vendoring the Dockerfile — must produce and hash a wheel first or the build fails.
- Negative / trade-off accepted: **there is no in-image rebuild-from-source path.** A security patch
  cannot be applied by rebuilding the image against fixed sources or by upgrading in place — `pip` is
  gone from the venv. The only supported route is: patch the source, rebuild the wheel, re-verify,
  rebuild the image. That is slower than Option B's rebuild, and it is the price of invariant 3.
  A patch to a *dependency* is cheaper: it moves `poetry.lock`, and the existing wheel can be reused.
- Negative / trade-off accepted: the caller now carries four coupled inputs instead of none, and any
  new caller must reproduce the derivation. The duplication between `justfile:43-57` and
  `.github/workflows/verify-build.yaml:461-493` is real; it is bounded by the in-build validation,
  which rejects a wrong derivation rather than trusting it.
- Follow-ups: `docker/README.md:22-48` and `docs/developer.md:135-151` document the direct Bake
  interface and must stay aligned with the invariants above; a change to the build-arg contract
  touches the Dockerfile, `docker-bake.hcl`, the `justfile`, the verifier, and both documents.

## Open questions

- **The in-build wheel contract has no dedicated test.** Invariants 1, 2, 4 and 7 are enforced by
  shell inside `docker/Dockerfile` and are exercised only implicitly, by the happy path succeeding
  in `just image` and in the verifier's image job. Whether to add a negative-path check — building
  with a wrong SHA-256, two wheels, or no wheel, and asserting the specific failure — is unresolved.
  Until then these are rules without a guard proving they still fire (Core §3).
- ~~**Multi-platform builds are untested against this contract.**~~ **Answered 2026-09-02** by
  the Epic 8 F13 spike, and answered affirmatively: the hash-verified wheel path behaves
  identically under an emulated multi-platform build, with **no Dockerfile change required**.

  The reason it holds is worth stating, because it is the property the whole contract rests on:
  the wheel is `py3-none-any`, so the *same file with the same SHA-256* is installed into both
  platform images. The `linux/arm64` builder passed the SHA-256 check, the VERSION-equals-metadata
  check and `pip check` exactly as `linux/amd64` did. Exact-wheel provenance is therefore
  platform-independent by construction, not by coincidence.

  Measured on 8 vCPU: `linux/amd64` alone 50 s; `linux/amd64,linux/arm64` emulated **436 s**
  (8.7×), of which 80 % is two `linux/arm64` steps under QEMU — `apk add gcc cargo` (203 s) and
  `poetry install --only main` (145 s). Nothing compiles Rust from source; the cost is interpreter
  and unpack overhead amplified by emulation. Budget 12–15 minutes on a 4 vCPU GitHub-hosted
  runner. A second native runner is not required on these numbers.

  One consequence for whoever asserts the published index: **`ATTESTATIONS = []`, the shipped
  default, does not disable attestations.** BuildKit emits SLSA provenance `mode=min` regardless,
  so the index carries four descriptors — two platforms plus two `unknown/unknown`
  attestation manifests. Adding `type=sbom` keeps it at four (the SBOM shares the per-platform
  attestation manifest); only `type=provenance,disabled=true` drops it to two. A count assertion
  is therefore wrong in three separate directions. Assert the filtered set instead, keying on the
  authoritative annotation rather than on the `unknown/unknown` compatibility convention:

  ```python
  platforms = {
      f"{m['platform']['os']}/{m['platform']['architecture']}"
      for m in index["manifests"]
      if m.get("annotations", {}).get("vnd.docker.reference.type") != "attestation-manifest"
  }
  assert platforms == {"linux/amd64", "linux/arm64"}
  ```

  Note the nesting level differs by source: `imagetools inspect --raw <ref>` returns the manifest
  list directly, while an OCI-layout `index.json` sits one level above it — and a single-platform
  layout has no nested index at all. A test iterating `index.json`'s `manifests[]` reads the wrong
  level.
