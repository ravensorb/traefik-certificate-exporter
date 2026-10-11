# ADR-0024: Atomic-write helper covers PKCS12 (`.pfx`) exports, not just PEM text files

- **Status:** Proposed
- **Date:** 2026-10-06
- **Deciders:** Maintainer (ravensorb)
- **Amended by:** ADR-0043 (the `.pfx` is built with the rest of the set before any replace, and is rewritten only when its content changed)
- **Epic:** E011
- **Departs from spec:** n/a
- **Principle(s) in tension:** ADR-0023's atomic-write decision (`tempfile.NamedTemporaryFile` +
  `os.replace`) vs. E011-S01-004's own Business AC promising every "certificate file on disk"
  is never left zero-length or partial.

## Context

E011-S01-004's Technical AC (Interface Contracts) enumerates exactly 8 `Path.open("w")`
call sites in `AcmeCertificateExporter.__exportCertificate`
(`src/traefik_certificate_exporter/libs/certificate_exporter.py`) to convert to a shared
atomic-write helper: `.key`, `.crt`, `.chain.pem`, `.fullchain.pem` (flat layout) and
`privkey.pem`, `cert.pem`, `chain.pem`, `fullchain.pem` (per-domain layout). It omits the
two PKCS12 `.pfx` export sites: `PemToPfxConverter.export_to_pkcs12` does
`Path(filename).write_bytes(pkcs12_bytes)` (truncate-then-write, no atomicity), fed from
`.pfx`/`cert.pfx` path construction in both layout branches of `__exportCertificate`.

The story's own Business AC states: "A process killed at any point during an export pass
leaves every certificate file on disk either fully in its previous state or fully in its
new state — never zero-length or partial." The `.pfx` file is a certificate file by this
same definition — it is derived from, and consumed as a substitute for, the PEM
`cert`/`fullchain` pair, loaded directly by services that prefer PKCS12 bundles (common for
Windows/IIS- and Java-keystore-facing consumers). A SIGKILL between `write_bytes`'s
truncate and write leaves exactly the same zero-length/partial hazard the PEM sites are
being fixed for, just on a different serialization format.

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Extend the atomic-write helper to also cover `write_bytes`-style writes, and route both `.pfx` sites through it | Same primitive (tmp file + `os.replace`, same directory) generalized to accept bytes or str; closes the hazard for all 10 sites with one helper; no asymmetric guarantee between PEM and PKCS12 outputs of the same pass | One more call site to migrate; helper needs a bytes-vs-text branch (or two thin wrappers over one core function) | Matches the Business AC's own "every certificate file" wording exactly; no carve-out to justify |
| B. Explicitly scope `.pfx` out as a non-goal, with a stated reason (e.g. "PKCS12 is regenerable/non-critical") | Less code to touch in this story | No real justification exists: `.pfx` is written from the same in-memory key/cert material as the PEM files in the *same* pass, at the *same* trust level, and is itself called a "certificate file" in the story's own Business AC — a carve-out here would be scope-shrinkage dressed as a decision, not a supported safety distinction | Contradicts the story's own stated outcome; rejected |

## Decision

**Option A.** The shared atomic-write helper is extended to accept both the existing
`str`-via-`.write()` case and a `bytes`-via-`.write_bytes()`-equivalent case (either one
helper with a mode parameter, or two thin functions sharing one core
`tempfile.NamedTemporaryFile(dir=..., delete=False)` + `os.replace` body), and
`PemToPfxConverter.export_to_pkcs12`'s `Path(filename).write_bytes(pkcs12_bytes)` call is
routed through it, in the same directory as the target `.pfx` file (so `os.replace` stays
on one filesystem, matching the constraint already called out for the text sites). This
is the same primitive already adopted for the other 8 sites, generalized by one parameter
— not a second mechanism — so it does not introduce new surface area the story would need
to separately justify. All 10 `Path.open("w")`/`write_bytes` sites are converted under one
helper, giving the Business AC's "every certificate file" promise uniform coverage rather
than a PEM-only subset.

## Consequences

- Positive: The write-safety guarantee in the Business AC is actually true for every file
  type the pipeline emits, not just PEM. One helper, one atomicity guarantee, one place to
  audit for permission parity (ADR-0023's existing security-consideration bullet about
  `os.replace` not copying permissions automatically) now also covers `.pfx`.
- Negative / trade-offs accepted: The helper's signature/implementation is marginally more
  general (bytes-or-str) than a PEM-only version would have been; the story's planted-
  failure test matrix (Testability approach) grows by one case (mid-`write_bytes` failure
  leaving the prior `.pfx` or no `.pfx`, never partial).
- Follow-ups / exit plan: none — this is a same-release scope correction, not a deferred
  capability.
