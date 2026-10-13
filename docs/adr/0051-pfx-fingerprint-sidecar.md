# ADR-0051: PKCS#12 change detection by fingerprint sidecar; optional RSA key validation

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** Maintainer (ravensorb), decision 2026-10-12 on BL-E014-106 and maintainer
  decisions MD-06/MD-07 (accepted 2026-10-12); implemented by E015-S01-002
- **Epic:** E015
- **Amends:** [ADR-0043](0043-export-commit-and-reporting-contract.md) Decision 2 (the PFX
  bullet and "There is no fingerprint store") and its Options table (option B)
- **Departs from spec:** n/a. Binds product spine AD-8 (key loading, change test, fingerprint
  file contract, writes, upgrade, state) and AD-10 (the fingerprint file is not an
  artifact); PRD NFR-8
- **Principle(s) in tension:** "the files on disk are the only state" (ADR-0043) against the
  cost of opening every `.pfx` on every pass; default-safe key validation against pass time
  on RSA-4096 stores

## Context

Traefik's ACME keys are RSA-4096. cryptography validates an RSA private key on every load
(~550 ms for RSA-4096 on cryptography 50.0.2, ~52 ms for RSA-2048), and
`pkcs12.load_key_and_certificates` validates the embedded key again and takes no skip flag.
Under ADR-0043 every pass loaded each domain's key twice (`__exportDomain` and
`build_pkcs12`) and, for an existing `.pfx`, loaded the bundle once more for the content
compare (twice with a passphrase). The live-host test on 2026-10-12 measured 74 s for a first
pass and 108 s for an unchanged pass over 74 certificates (BL-E014-106). The test fixtures
used EC P-256 keys, so no test showed the cost.

The `.pfx` cannot be compared by bytes: two builds of the same input never match, with or
without encryption (ADR-0043 Decision 2; `test_encrypted_pfx_builds_differ_byte_for_byte`).
The content compare is what costs a PKCS#12 load per domain per pass.

## Options considered

| Option | For | Against |
|---|---|---|
| A. Keep the content compare; only drop the second key load | Smallest change | An unchanged pass still loads every key and every `.pfx`: ~41 s of key validation alone for 74 domains |
| B. Skip RSA validation always | Fast | Unsafe for keys not written by the operator's own Traefik (cryptography: "User supplied keys should never be loaded with this parameter set to True") |
| C. Fingerprint sidecar per `.pfx`, lazy key load, optional validation (`validatekeys`) | Unchanged pass loads nothing; validation stays on by default; the sidecar is checked against the file, never trusted alone | One more file per `.pfx`; one slower verify pass after upgrading from 0.3.0 |

Option C. There is deliberately no toggle for the change test: the sidecar path is the only
path.

## Decision

1. **Lazy key load (D1).** For every domain the cheap steps run first: strict base64 decode,
   chain parse, containment check and sweep, PEM byte compare. Then the `.pfx` state is
   computed from its sidecar (`_pfx_state`: `current`, `rebuild` or `verify`). Only for
   `rebuild` or `verify` is the key loaded -- once, through `_load_private_key(keyPem,
   validate)` -- and the bundle serialised through `_serialize_pkcs12`. Build-first
   (ADR-0043 Decision 1) holds: every artifact that will be written is built before the first
   write, and a failure at stage `key` or `pkcs12` writes nothing, PEMs included.
2. **`settings.validatekeys`** (default `true`; env
   `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_VALIDATEKEYS`; CLI `--no-validate-keys`).
   `_load_private_key` passes `unsafe_skip_rsa_key_validation=not validate`. `false` is only
   for a store written by the operator's own Traefik: the keys are then trusted, not checked.
   The key/certificate match is not part of that validation and stays in both modes:
   `pkcs12.serialize_key_and_certificates` raises on a mismatch (stage `pkcs12`).
   `PemToPfxConverter.build_pkcs12` (public API) keeps its signature and always validates.
   Toggling the setting rebuilds nothing. Root-trust class: `any-source`
   ([ADR-0049](0049-root-mode-trust-covers-hook-output-and-store-location.md)).
3. **The change test for the `.pfx`** (replaces ADR-0043 Decision 2's PFX bullet on the
   normal path). The `.pfx` is *current* iff it passes the write policy, its sidecar is
   usable, the sidecar's `pfx_sha256` equals the SHA-256 of the `.pfx` on disk, `key_sha256`
   equals the SHA-256 of the store's decoded key PEM, `certificates_sha256` equals the
   ordered SHA-256 fingerprints of leaf and intermediates, and the passphrase state matches
   (`null` exactly when none is configured, otherwise `Scrypt.verify` succeeds). A usable
   sidecar with an input mismatch gives `rebuild` (no PKCS#12 load). A missing `.pfx`, or a
   non-regular file at its path, gives `rebuild`. A missing or unusable sidecar, or a
   `pfx_sha256` mismatch, gives `verify`: ADR-0043's content compare (`_pfx_differs`) runs
   once; current content writes only the sidecar and reports nothing, differing or unreadable
   content rebuilds the `.pfx` and reports the domain.
4. **Sidecar contract (D3).** Path `<pfx path>.fingerprint.json`, derived only by
   `_pfx_fingerprint_path` beside `_artifact_paths`. UTF-8 JSON (`sort_keys`, trailing
   newline): `format` `traefik-certificate-exporter/pfx-fingerprint`, `version` 1,
   `pfx_sha256`, `key_sha256`, `certificates_sha256`, and `passphrase`: `null` or
   `{"kdf": "scrypt", "n": 16384, "r": 8, "p": 1, "salt": <base64 16 bytes>, "digest":
   <base64 32 bytes>}`. A sidecar that is absent, not a regular file, still too permissive
   after the in-place tighten, larger than 64 KiB, not UTF-8 JSON, or of an unknown format,
   version or field type is unusable; that is never an error.
5. **Passphrase hash (D4).** cryptography's `Scrypt` with a random 16-byte salt per sidecar
   written. `_passphrase_matches(passphrase, record)` is not cached and validates the record
   first (unknown or malformed gives `False` with no derive; the implementation also bounds
   the cost parameters, scrypt memory `128 * n * r` at 64 MiB and `p` at 16, so a planted
   sidecar cannot force an unbounded allocation). `_scrypt_verifies(passphrase, salt, n, r,
   p, digest)` is a `functools.lru_cache(maxsize=4096)` over hashable primitives, so each
   sidecar costs one derive per process (arch gate AG-3).
6. **Write order (D5).** Changed PEMs, then the `.pfx`, then the sidecar, each atomically at
   0600 (`_atomic_write_bytes`, ADR-0023/0024). The sidecar is written whenever the `.pfx`
   was written or verified current. A failed sidecar write logs one WARNING and changes
   nothing else; the next pass verifies. A crash between the `.pfx` and its sidecar leaves a
   stale sidecar whose `pfx_sha256` no longer matches: the next pass verifies, writes the
   sidecar and reports nothing. It never yields a false "unchanged".
7. **Not an artifact.** The sidecar is not one of the five recorded artifact paths
   (ADR-0040), so `artifactMtime` and the restart rule
   ([ADR-0045](0045-restart-policy-only-on-change-defer-not-drop.md)) never see it. Writing only a
   sidecar never reports a domain. ADR-0045 is unchanged.
8. **Upgrade from 0.3.0 (D2).** Output without sidecars takes the verify path once per
   `.pfx`: no artifact is rewritten (inodes and mtimes unchanged), one sidecar per `.pfx` is
   written, no domain is reported, so no restart, hook or notification follows. Output from
   0.2.x still fails the content compare (no intermediates) and gets the one-time rewrite.
9. **Dry run** computes the state and runs the verify compare as usual and writes nothing,
   sidecars included. A dry run over 0.3.0 output therefore verifies every `.pfx` until a
   real pass has written the sidecars.
10. **Start-up line (D6).** One INFO after `Output Path`: `RSA key validation: on` or
    `RSA key validation: off (settings.validatekeys=false: keys are trusted, not checked)`.

## Why this is not ADR-0043's rejected option B

ADR-0043 rejected a fingerprint store as "a second source of truth that drifts from the files
consumers read". The sidecar is never authoritative alone: "current" requires its recorded
`.pfx` hash to equal the file on disk, and a missing or unusable sidecar, or one whose
`pfx_sha256` does not match, falls back to the content compare. An operator who edits,
replaces or truncates a `.pfx` still gets it rebuilt (self-heal); an operator who deletes the
sidecars costs one verify pass. An operator who edits a usable sidecar's recorded inputs while
leaving `pfx_sha256` intact gets a rebuild and a reported domain (Decision 3's input-mismatch
case), not a silent verify. The PEMs
keep their byte compare against the files. An attacker who can rewrite both the `.pfx` and
its sidecar can also rewrite `privkey.pem`, so no trust boundary is crossed.

## Consequences

- An unchanged pass performs no private-key load and no PKCS#12 load, whatever
  `validatekeys` is set to (with a passphrase, at most one ~63 ms scrypt check per sidecar per
  process). `validatekeys` only affects passes that build or verify a `.pfx`.
- One extra file per `.pfx`, mode 0600, holding hashes only (no passphrase, no key bytes).
  Stale sidecars of domains that leave the store are not removed, like the artifacts.
- `PemToPfxConverter.export_to_pkcs12` writes no sidecar; a `.pfx` it writes into the output
  directory is verified once by the next pass.
- The DEBUG `.pfx` introspection reads the in-memory certificates and loads nothing.

## Evidence

E015-S01-002 tests in `tests/libs/test_certificate_exporter.py`
(`test_unchanged_rsa4096_pass_loads_no_key_and_no_pfx`,
`test_first_rsa4096_pass_loads_each_key_once`, `test_upgrade_from_0_3_0_output_verifies_once_and_rewrites_nothing`,
`test_passphrase_change_is_detected_from_the_sidecar_alone`, the sidecar tests) and the
measurements in
`_bmad-output/implementation-artifacts/epic-015/sprint-01/closure/notes-E015-S01-002.md`.

## Revisit when

- cryptography offers a validation skip for `pkcs12.load_key_and_certificates`, or makes RSA
  validation cheap enough that the content compare costs little; or
- the `.pfx` build becomes deterministic, so a byte compare works.

## Amendment (2026-10-12) — sprint closure

Finding AR-4 (`_bmad-output/implementation-artifacts/epic-015/sprint-01/closure/adversarial-review.md`).

The sidecar recorded the inputs of the `.pfx` but not how it was built, so a future change to
`_serialize_pkcs12` (friendly name, encryption, intermediates) would never reach a `.pfx`
whose sidecar is usable: `_pfx_state` returns `current` and the content compare never runs.

- **Decision 4 gains one field:** `builder`, an integer, written as `_PFX_BUILD_RECIPE`
  (currently `1`). Every other field and the unusable-sidecar rules are unchanged; a sidecar
  without `builder` is still usable (the format `version` stays 1).
- **Decision 3 gains one rule:** a usable sidecar whose `builder` is absent, not an integer,
  or not equal to `_PFX_BUILD_RECIPE` gives `rebuild`, checked before the `.pfx` hash. The
  `.pfx` is rebuilt once and the domain reported (hook, notification, restart as for any
  rebuild); the new sidecar records the current recipe, so the next pass is `current`.
- **Changing the recipe requires bumping `_PFX_BUILD_RECIPE`.** Mechanically checked:
  `tests/libs/test_certificate_exporter.py` pins a SHA-256 of `_serialize_pkcs12`'s source
  per recipe value and fails when the source changes. The test forces a decision, not the
  bump: a change that does not alter the bundle may re-pin the hash for the same value, and
  that judgement is review. A recipe change made outside `_serialize_pkcs12` (in a caller,
  or by a cryptography upgrade changing `BestAvailableEncryption`) is not detected.
- **Upgrade impact:** sidecars first ship in this release (Decision 8: 0.3.0 output has none),
  so no released sidecar lacks `builder`; only sidecars from pre-release builds of this
  release are rebuilt once.
