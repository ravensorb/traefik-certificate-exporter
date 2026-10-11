# ADR-0040: Exported-artifact paths come from one shared helper, keyed by the parsed store

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** E014 epic architecture gate (l3io-arch-review + bmad-agent-architect)
- **Epic:** E014
- **Departs from spec:** n/a. Binds the artifact-lookup half of product spine AD-10
  (`_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md#ad-10--container-restart-one-client-file-mtime-trigger-defer-not-drop-adopted`)
  and PRD FR-15; resolves arch-gate findings AG-1 and AR-3
  (`_bmad-output/implementation-artifacts/epic-014/arch/arch-gate-review.md`,
  `arch-gate-review-architect.md`)
- **Principle(s) in tension:** Core §3 Design by contract (the restart reader must find
  exactly what the writer wrote); Core §2 Reuse (one path rule, not two copies); Global
  rule 4 (derive the scope from the source of truth, never re-enumerate it)

## Context

E014-S01-006 makes a container restart depend on the newest mtime of the files exported
for its labeled domains (AD-10, FR-15). As planned, it looked those files up with
`artifactMtime(domain)` over "the `flat` or per-domain directory" layout. The writer does
more than that (`src/traefik_certificate_exporter/libs/certificate_exporter.py:428-445`,
checked 2026-10-11):

- the base is `outputPath`, or the current directory when it is unset;
- a resolver directory is inserted when `resolverInPathName` is true **and** the store
  node being exported has a resolver name;
- the domain directory is added unless `flat` is true; in flat mode the files are
  `<name>.key|.crt|.chain.pem|.fullchain.pem|.pfx`, otherwise
  `privkey.pem|cert.pem|chain.pem|fullchain.pem|cert.pfx`;
- `name` is the certificate's main domain with a leading `*.` removed.

`resolverinpathname: true` is the default (`src/traefik_certificate_exporter/config_default.yaml:6`,
and both sample configs). So the default layout is `<base>/<resolver>/<domain>/`, which the
planned lookup never examined. Under the default configuration it would have returned
`None` for every domain, no container would have been a candidate, and no restart would
have happened: the B1 silent no-op again.

Four layouts exist, and which one applies depends on the store as well as on settings:

| `resolverInPathName` | store node has a resolver name | `flat` | Files |
|---|---|---|---|
| true | yes (Traefik v2/v3 resolver-wrapped store) | false | `<base>/<resolver>/<name>/privkey.pem` … |
| true | yes | true | `<base>/<resolver>/<name>.key` … |
| false, or true with no resolver name (unwrapped v1.7 `StoredData`, uppercase-key stores) | — | false | `<base>/<name>/privkey.pem` … |
| as above | — | true | `<base>/<name>.key` … |

The same domain can also appear under two resolvers, which gives two directories.

AR-3 adds a scoping question. A watch drain processes one store file
(`AcmeCertificateFileHandler.__processPath`, `certificate_exporter.py:1044-1065`), but the
restart rule is evaluated over every labeled container. The lookup has to say which store
files' domains it can answer for.

## Options considered

| Option | Pros | Cons | Standards fit |
|---|---|---|---|
| A. `artifactMtime(domain)` re-derives the paths from settings alone (the plan as written) | No state | Cannot know the resolver name; wrong for unwrapped stores; a second copy of the path rule that drifts from the writer | Violates Core §3 and Global rule 4; this is AG-1 |
| B. Glob the output tree (`<base>/*/<domain>/…`, `<base>/<domain>.*`) | No state; finds files from earlier processes | Matches files the exporter did not write; cannot tell a resolver directory from a domain directory in flat mode; still a second, hand-written path rule | Violates Global rule 4; trusts untrusted directory contents for the candidate set |
| C. One pure helper names a domain's artifact paths from `(base, resolverName, name, flat, resolverInPathName)`; the writer uses it; the export pass records the paths it produced or kept per domain; `artifactMtime` reads that record | Reader and writer cannot disagree; resolver and store shape come from the parsed store; no glob | In-memory record; a store file not yet processed by this process contributes nothing | Honours Core §2, §3 and Global rule 4 |
| D. Option C, but re-parse every store file under `datapath` on every restart evaluation | Covers every store file on every pass | Doubles parse work per drain; re-implements the iteration the export pass already did | Duplicates work without changing the answer after the start-up pass |

## Decision

Option C.

1. **One path helper.** `certificate_exporter.py` gets a module-level pure function,
   `_artifact_paths(base: Path, resolverName: str | None, name: str, *, flat: bool, resolverInPathName: bool) -> list[Path]`.
   It returns the five artifact file paths for one certificate in the fixed order key,
   certificate, chain, full chain, PKCS12. It inserts the resolver directory only when
   `resolverInPathName` is true and `resolverName` is a non-empty string, and adds the
   `name` directory only when `flat` is false. It reads no settings object and touches no
   filesystem.
2. **The writer uses it.** `__exportCertificate` takes every target file name from
   `_artifact_paths`, and its directory (for `mkdir`, the stale-temp sweep and the
   `_is_contained_within` check) from the parent of those paths. No other code in `src/`
   joins `outputPath`, a resolver name and a domain name.
3. **The inputs come from the parsed store.** `resolverName` is exactly the value
   E014-S01-003's `_iter_resolver_nodes` yields for the node (`None` for an unwrapped
   store), after `traefikresolverid` scoping. `name` is the exported name after the `*.`
   strip and `_is_safe_path_component`. Nothing re-derives either from settings.
4. **The export pass records what it produced or kept.** The exporter holds an index
   `sourceFile → {name → set[Path]}`. Processing a store file replaces that file's entry
   with the `_artifact_paths` result of every certificate that reached the write step,
   whether its files were rewritten or left unchanged (E014-S01-002). Domains filtered
   out by `domains.include`/`exclude`, refused by the path-safety checks, or failing to
   build are not recorded. A file-level failure (missing, empty, invalid JSON) leaves the
   previous entry for that file in place, so a half-written store does not drop
   containers from candidacy. A dry run records the same paths it would write.
5. **The reader reads the record.** `artifactMtime(domain)` returns the newest
   `os.stat(...).st_mtime` over the union of recorded paths for `domain` across every
   store file in the index, or `None` when there are none or none exists on disk. An
   `OSError` on one path counts as missing. When the same domain is exported under two
   resolvers, the newest file across both wins.
6. **Scope of one pass (AR-3).** The index covers every store file this process has
   processed, not only the file of the current drain. With `runatstart: true` (the
   default) the start-up pass processes every file under `datapath`, so from then on each
   drain evaluates containers for the domains of all store files. With
   `runatstart: false`, a store file that has not been written since the process started
   has no entry, and its containers are not candidates until its next write. "Recovered
   on the next pass" in AD-10 and `docs/operational.md` means: the next start-up pass, or
   the next write of any store file once that store file has been processed in this
   process.

## Consequences

- Positive: the restart lookup finds artifacts under the default layout, in flat mode
  with and without a resolver directory, and for unwrapped stores. Changing the layout
  rule is a change to one function, and the writer's tests then cover the reader.
- Positive: no glob over the output directory, so files the exporter did not write never
  make a container a candidate.
- Trade-off accepted: the index is process memory. It is rebuilt by the start-up pass,
  which is also what crash recovery relies on (AD-10). An entry for a store file that was
  deleted while the process runs stays until the process restarts; its files' mtimes do
  not move, so it causes no restart.
- Trade-off accepted: with `runatstart: false`, a crash-lost restart for a store file is
  recovered only after that store file is next written. This is stated in
  `docs/operational.md` by E014-S01-006.
- Follow-up: PRD FR-3 and the product spine Conventions "Data & formats — artifacts" row
  do not mention the resolver directory. E014-S01-006 routes that text to E014-S02-003
  through its notes file.
- Tests: unit cases cover all four layout rows above, a two-resolver same-domain store
  and an unwrapped store. The image-level test in E014-S01-006 uses a resolver-wrapped
  store, the stock Traefik v2/v3 shape, under the image's default settings.

## Revisit when

- the exporter persists state between processes (then the index can be persisted and the
  `runatstart: false` caveat removed); or
- a new output layout setting is added (it goes into `_artifact_paths`, nowhere else).
