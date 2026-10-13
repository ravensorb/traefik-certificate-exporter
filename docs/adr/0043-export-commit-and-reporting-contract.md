# ADR-0043: Export commit and exported-domain reporting contract

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** Maintainer (ravensorb), decision "restart only on change" (2026-10-11);
  implemented by E014-S01-002; decision 6 (per resolver and per file) by E014-S01-003
- **Epic:** E014
- **Amends:** ADR-0014 §Decision ("notified with the exported domain list"), ADR-0023
  Decision 3, ADR-0024
- **Departs from spec:** n/a. Binds product spine AD-8 (artifact set, build before write,
  rewrite only on change, the changed signal) and PRD FR-2/FR-14; resolves review findings
  B2 and M4 (the build-first half) and backlog item BL-E012-008
- **Principle(s) in tension:** per-file atomicity (ADR-0023/0024) against a set of five
  files that is not transactional; "the files are the state" against a fingerprint store

## Context

Until 0.3.0 every pass rewrote all five artifacts of every domain and reported every
domain, so nothing downstream could tell a renewal from a no-op pass. A drain triggered by
any store write reported every domain, which is why name-based change detection for
container restarts was tried and reverted (BL-E012-008).

The PKCS12 bundle was also built last, after the four PEM files had already been replaced.
When it failed -- and with a passphrase set it always failed, because the unencrypted ACME
key was loaded *with* the passphrase (B2) -- the domain was left with a rotated key next to
a stale `.pfx`, and it was not reported, so no restart, hook or notification followed.

## Options considered

| Option | For | Against |
|---|---|---|
| A. Keep rewriting everything; report every domain | No new logic | No change signal; restarts and notifications on every pass |
| B. Fingerprint store (hash per artifact in a state file) | Cheap comparison | A second source of truth that drifts from the files consumers read; lost or stale state after an operator edits a file or the state file is lost |
| C. Compare the built artifacts with the files on disk | The files consumers read are the only state; survives restarts; operator edits self-heal | The PFX cannot be compared by bytes (fresh salt/IV per encrypted build), so it needs a content comparison |

Option C.

## Decision

1. **Build before replace.** For each domain, the exporter decodes the key and full chain,
   parses the chain with `cryptography.x509.load_pem_x509_certificates`, and serialises the
   PKCS12 bundle (with the intermediates, AES-256/SHA-256 via `BestAvailableEncryption`
   when a non-empty passphrase is set, unencrypted for `None` or `""`) before the first
   write. A domain that fails to build writes nothing, logs one ERROR naming the failure
   class (key, certificate chain, pkcs12), and is not reported.
2. **The change test.** Each built artifact is compared with the file already on disk:
   - PEM artifacts (key, cert, chain, full chain; flat `.key/.crt/.chain.pem/.fullchain.pem`):
     changed if the file is absent, unreadable, or its bytes differ.
   - PFX: changed if the file is absent or cannot be loaded with the configured
     passphrase, if its encryption state differs (it loads without a passphrase while one
     is configured), or if its content differs: the PKCS8 DER of the key, the leaf DER, or
     the ordered intermediate DERs. The encryption algorithm and iteration count are not
     compared.
   - Any artifact that the write path would not keep as it is -- a symlink or other
     non-regular file at the export path, or a mode more permissive than the artifact's
     floor (0600 for key-bearing files) -- counts as changed, so skipping unchanged files
     never freezes a state the rewrite used to correct.
   The files on disk are the only state. There is no fingerprint store.
3. **Write only what changed.** Unchanged artifacts are not rewritten: their inode and
   mtime stay the same. Atomicity stays per file (ADR-0023 Decision 3, ADR-0024); the set
   as a whole is not transactional.
4. **Reporting.** A domain is reported -- in the list `exportCertificatesForFile` returns,
   and so to the post-export hook and notifications (amending ADR-0014's "exported domain
   list") -- if and only if at least one of its artifacts changed on disk in this pass. If
   a write fails after one or more artifacts were replaced, the domain is reported and one
   ERROR names the artifacts written and not written; the next pass sees the remaining
   differences and writes them. If the first write fails, nothing changed and the domain
   is not reported.
5. **Dry run** builds and compares the same way, writes nothing, and reports a domain whose
   build succeeded and at least one of whose artifacts would change.

6. **Per resolver and per file** (added by E014-S01-003, which also resolves review finding
   M4's per-resolver half, M3 and BL-E011-018):
   - **Shape, not CA.** A resolver node is a dict with an `Account` or `Certificates` key,
     in either case; a top level that is itself one (Traefik v1.7, or an unwrapped v2) is
     a single store with no resolver name. Legacy ACME-v1 certificates come from
     `DomainsCertificate.Certs`, at node level or under `Account`. `Registration.uri` is
     never used to decide anything; it names the CA account (Let's Encrypt, ZeroSSL,
     Google, step-ca) and is logged at DEBUG only. Each entry's key case
     (`domain.main`/`Domain.Main`, `key`/`Key`, `certificate`/`Certificate`) is chosen by
     the keys that entry has.
   - **Null-safe.** `"Certificates": null`, `"Account": null`, `"Registration": null` and a
     missing `uri` export whatever is present and raise nothing.
   - **Isolation.** Each resolver is exported inside its own `try`. A failure logs one
     ERROR naming the (sanitized) resolver and the exception class, and never discards
     the domains other resolvers reported. After the resolvers, one WARNING
     `N of M resolvers failed in <file>` is emitted when N > 0.
   - **Return value.** `exportCertificatesForFile` returns `list[str]`, never `None`: the
     de-duplicated union of each resolver's reported domains, where each resolver reports
     exactly as decision 4 says (only domains with a changed artifact). A file that is
     missing, empty, not valid JSON, or nested too deeply to parse returns `[]` with one
     ERROR; a file with no resolver node returns `[]` with one WARNING; a top-level value
     that is not a resolver node is skipped with a WARNING.
   - **Strict base64.** Every base64 field is decoded with `validate=True`. An invalid
     value fails that certificate only: one ERROR naming the domain and the field, and
     nothing written for it.
   - **One owner per set of files, within one store file.** Two entries map onto the same
     files when two resolvers hold one domain and `resolverinpathname` is off, or when one
     resolver holds both `example.test` and `*.example.test` (the wildcard prefix is
     stripped from the name). Exporting both made them overwrite each other on every pass
     (BL-E014-012). An entry whose stored main domain or SANs cover the name the files
     are written under beats one that does not, so a wildcard without an apex SAN never
     becomes the apex's files (amended by ADV-4, E014 sprint 01 closure). Among those,
     the entry whose leaf expires last owns the files; on a tie, the first
     in store order does (Traefik writes the resolver map with sorted keys, so the order is
     stable and an unchanged store stays quiet). Each other entry is skipped with a
     WARNING naming both entries and their expiry dates. With `resolverinpathname` on,
     two resolvers have separate files and both are exported. Separate store files that
     hold the same domain are not compared with each other: the file processed last wins,
     as before.
   - **No size limit.** The store is read whole. It is trusted Traefik output, and anyone
     who can write `/data` can already do worse than supply an oversized file -- replace
     the certificates being exported, for example. RT-014's `st_size` guard is declined
     on that basis (maintainer decision 2026-10-11). Mounting `/data` `:ro` is defence in
     depth only: it is documented, not enforced, and under ADR-0030 as amended the stock
     deployment runs as root, where it is not required.

The restart rule that depends
on decision 3 (newest artifact mtime against the container's `StartedAt`) is recorded by
E014-S01-006's ADR; the hook and notification policy that consumes decision 4 is extended
there by E014-S01-010.

## Consequences

- A pass over an unchanged store writes nothing and reports nothing.
- A domain held by two resolvers with `resolverinpathname` off is exported from the entry
  that expires last, so a stale resolver left in the store after a migration (HTTP-01 to
  DNS-01, say) does not keep serving its older certificate. A wildcard and its apex in
  one resolver share one directory; the apex entry is exported unless the wildcard also
  lists the apex as a SAN, and then the one that expires last is, which may be
  a different certificate than 0.2.x left on disk (there, the last entry written won).
- `exportCertificatesForFile` rejects `OSError`, `ValueError` (including too-deep JSON)
  and `MemoryError` at file level with `[]` and an ERROR; anything else propagates.
- One broken or empty resolver no longer hides the other resolvers' domains from the
  restart, the post-export hook and notifications.
- The first pass after upgrading from 0.2.x rewrites every `.pfx` (it now carries the
  intermediates), so every domain counts as changed once.
- An operator who edits or deletes an exported file gets it rewritten, and the domain
  reported, on the next pass. That is intended.
- An encrypted `.pfx` requires a consumer that reads AES-256/SHA-256 PKCS12: Windows 10
  1709+/Server 2019+, OpenSSL 3 or current macOS. Windows Server 2016 and older cannot
  import it; a legacy 3DES option is not offered until requested.
- Evidence: `tests/libs/test_certificate_exporter.py` (the change-signal, build-first and
  passphrase tests, including `test_encrypted_pfx_builds_differ_byte_for_byte`, which
  shows the design premise holds on the locked `cryptography`) and the image-level
  `tests/test_container_pkcs12.py`.
- Evidence for decision 6: the store-shape tests in
  `tests/libs/test_certificate_exporter.py` (`test_zerossl_v3_store_is_exported` through
  `test_the_entry_that_expires_last_owns_shared_files`).

## Amendment (2026-10-12) — ADR-0051

[ADR-0051](0051-pfx-fingerprint-sidecar.md) replaces Decision 2's PFX bullet on the normal
path, and with it "There is no fingerprint store". Each `.pfx` has a fingerprint sidecar,
`<pfx path>.fingerprint.json` (0600, hashes only: the `.pfx` file, the key PEM, the
certificates, and the passphrase as a salted scrypt hash). The `.pfx` is current when the
sidecar is usable, its recorded `.pfx` hash equals the file on disk and every input hash and
the passphrase state match; then nothing is loaded or built. A usable sidecar with an input
mismatch rebuilds the `.pfx`. A missing `.pfx` is rebuilt. A missing or unusable sidecar, or a
`.pfx` hash mismatch, runs this ADR's content compare once: current content writes only the
sidecar and reports nothing; differing or unreadable content rebuilds the `.pfx` and reports
the domain. The sidecar is never authoritative alone, so this is not option B: a damaged or
edited `.pfx` still self-heals. The private key is loaded only when the `.pfx` is rebuilt or
verified, once, with RSA validation controlled by `settings.validatekeys` (default `true`).
The PEM change test, Decisions 1 and 3-6 and the consequences above are otherwise unchanged;
the sidecar is not an artifact and never moves the restart mtime (ADR-0045 unchanged).
