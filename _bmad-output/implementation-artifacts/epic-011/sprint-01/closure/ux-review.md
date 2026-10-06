# UX Review — Reviewer Gate (CLI / operator UX)

- **Reviewer:** Sally (bmad-agent-ux-designer → `bmad-ux` Reviewer Gate, headless)
- **Lens:** CLI & operator-output UX — single ad-hoc lens. The rubric walker and the
  `finalize_reviewers` lenses were not dispatched: they validate a `DESIGN.md` /
  `EXPERIENCE.md` spine pair, and no spine pair exists for this project. The UI under
  review is a console entry point and its log output, so the gate ran one lens shaped to
  that surface.
- **Scope:** `_bmad-output/implementation-artifacts/epic-011/sprint-01/stories/E011-S01-003.md`
  — "CLI and settings hardening: unrecognized-arg failure, settings-dump redaction"
- **Inputs read:** `src/traefik_certificate_exporter/libs/cli_args.py`,
  `src/traefik_certificate_exporter/app.py`,
  `src/traefik_certificate_exporter/libs/settings.py`, `README.md`,
  `docs/adr/0025-strict-cli-parse-without-import-time-regression.md`,
  sprint diff hunks for the above.
- **Method:** static read plus live execution of the installed console script
  (`poetry run traefik-certificate-exporter`) on Python 3.11.11 — typo flag, `--help`,
  and two DEBUG runs (one with a planted passphrase and Apprise URL, one with neither).
- **Run at:** 2026-10-06T16:40-04:00
- **Constraint honoured:** report only; no code, docs, or tests were changed.

## Overall verdict

The story's headline promise lands. A mistyped flag now does exactly what an operator
expects — `traefik-certificate-exporter --dtaa-path /tmp` prints a usage block, names the
offending argument verbatim (`error: unrecognized arguments: --dtaa-path /tmp`), and exits
`2`. No stack trace, no silent swallow. `--help` still exits `0`; the normal non-error
path is byte-for-byte what it was. ADR-0025's dual-path split is the right call and the
import-time leniency it protects is intact. That half of the story is **adequate-to-strong**.

The redaction half is where an operator gets hurt, and it is not a leak — the planted
`SUPERSECRETPASS123`, `CLIPASS999` and `tgram://SECRETTOKEN123/456` appear in **zero** log
records across all three sinks, so the security obligation (BL-E010-003) genuinely holds.
The problem is the opposite failure: the dumps redact **by key, unconditionally**, so a
secret that was never configured at all renders identically to one that was. An operator
debugging "why did no notification fire?" reads `appriseurls: REDACTED` and concludes
notifications are configured when nothing is. The dump answers "is this field secret?"
when the operator asked "is this field set?" That is a **high**-severity readability defect
sitting inside an otherwise correct security control, and it is precisely the question this
gate was asked to test: *can an operator tell a value was redacted rather than empty?*
Today, no.

Secondary theme: the error path is correct but minimal. It names the bad flag and never
suggests the good one, and the usage block it now prints on every typo is the most-read
surface of this CLI — yet it exposes internal config-path plumbing (`SETTINGS.DATAPATH`,
`SETTINGS.PKCS12PASSPHRASE`) as its metavars. `README.md` was left untouched by this story
despite the story's own "Files in scope" flagging it for exactly this reason.

### Category verdicts

| Category | Verdict |
| --- | --- |
| Unrecognized-flag failure & exit code | strong |
| Error discoverability (hint, near-match) | thin |
| Settings-dump readability | thin |
| Redaction unambiguity | **broken** (redacted vs. unset indistinguishable) |
| Redaction correctness (no leak) | strong |
| README / `--help` consistency | thin |
| Normal-path regression | strong (none found) |

---

## Findings

### UX-001 — High — A redacted secret is indistinguishable from one that was never set

**Operator-visible problem.** `_redact_secrets` substitutes `***REDACTED***` based on the
*key* alone, with no regard for whether the value exists. Verified live: a config file
containing **neither** `pkcs12passphrase` **nor** `appriseurls` still produces

```
DEBUG : Current Settings (active)...
DEBUG : {... "pkcs12Passphrase": "***REDACTED***", "postExportCommand": null, "appriseUrls": "***REDACTED***"}
DEBUG : Current Config (from file)...
        settings:
            appriseurls: REDACTED
```

An operator raised `-ll DEBUG` specifically to answer "is my notification/passphrase config
actually loading?" and the dump tells them, falsely, that both are populated. The same
output is produced whether the value is a real credential, an empty string, an empty list,
or absent entirely. Worse, the two sinks disagree on the absent case — confuse's
`dump(redact=True)` omits `pkcs12passphrase` from the file-config dump when unset, while
`_dump_settings` prints `***REDACTED***` for it, so the operator sees "absent here, set
there" for one and the same unset field. Every neighbouring unset field (`traefikResolverId`,
`postExportCommand`) renders honestly as `null`, which makes the redacted pair read as
"configured" by contrast.

This costs real debugging time on the highest-stakes fields in the product, and it is the
one question an operator cannot otherwise answer without reading the config by hand —
which is what the DEBUG dump exists to avoid.

**Remedy.** Make redaction value-aware in `_redact_secrets` (`src/traefik_certificate_exporter/libs/settings.py`):
substitute `_REDACTED_VALUE` only when the value is actually present, and pass empty values
through unchanged so they render as `null` / `[]` / `""`:

```python
if _SECRET_FIELD_PATTERN.search(str(key)) or _is_declared_secret(key):
    return _REDACTED_VALUE if val not in (None, "", [], {}) else val
```

Emitting `null` for a never-set secret discloses nothing — the absence of a credential is
not a credential. For the confuse sink, which is library-owned, the same outcome is reached
by only setting `view.redact = True` for declared paths whose `.get(confuse.Optional(...))`
is non-empty, leaving unset paths to render as they would otherwise. Extend
`test_every_declared_secret_key_is_redacted_in_every_sink` with an unset-value twin asserting
that an unconfigured secret renders as `null`/absent and *not* as `***REDACTED***`.

---

### UX-002 — Medium — Redacting a list collapses it to a scalar, destroying the only non-secret signal it carries

**Operator-visible problem.** `appriseUrls` is a list. Both dumps replace the whole list
with a single string: `"appriseUrls": "***REDACTED***"` and `appriseurls: REDACTED`. The
*count* of configured notification destinations and their *schemes* (`tgram://`, `mailto://`,
`discord://`) are not credentials, but they are the only facts that let an operator confirm
"my three notification backends loaded, and one of them is Telegram". Collapsing the
container also changes its apparent type — a YAML list reads as a scalar string in the dump,
so an operator copying the dump shape back into `config.yaml` would write it wrong.

**Remedy.** Redact per element, preserving container shape and cardinality. In
`_redact_secrets`, when a declared-secret key holds a list, return a list of the same length
whose entries keep the scheme prefix and mask the remainder — e.g.
`["tgram://***REDACTED***", "mailto://***REDACTED***"]`. If preserving the scheme is judged
too risky, the minimum acceptable form is `"***REDACTED*** (2 entries)"`, which at least
answers "how many?". Add a test asserting the element count survives redaction while no
substring of a planted URL's token does.

---

### UX-003 — Medium — The failure names the wrong flag but never suggests the right one, and never points at `--help`

**Operator-visible problem.** The live error is:

```
traefik-certificate-exporter: error: unrecognized arguments: --dtaa-path /tmp
```

It identifies the offender and nothing else. `--dtaa-path` is one transposition away from
`--data-path`, and the near-match is trivially computable, but the operator is left to scan
a 13-line wrapped usage block to find it. There is also no explicit "try
`traefik-certificate-exporter --help`" closing line — `[-h]` appears inside the usage block,
which is discovery by implication, not by instruction. argparse's own `suggest_on_error`
would cover this, but it landed in Python 3.14 and this project runs 3.11.11, so it is not
available by default.

**Remedy.** Subclass `argparse.ArgumentParser` in `cli_args.py` and override `error()` to
enrich the message before delegating to `super().error()`. Extract the offending tokens
starting with `-` from the message, run `difflib.get_close_matches(token, self._option_string_actions, n=2, cutoff=0.6)`,
and append `Did you mean --data-path?` when a match is found, plus a constant
`Run 'traefik-certificate-exporter --help' to see all options.` line in every case. This
changes no flag name, `dest=`, default, or help text, so it stays inside the story's stated
non-goals. Add a test asserting the `SystemExit(2)` message for `--dtaa-path` contains
`--data-path`.

---

### UX-004 — Medium — The usage block, now shown on every typo, leaks internal config paths as metavars

**Operator-visible problem.** Every option that takes a value advertises its internal
dotted `dest=` string, uppercased, as its placeholder:

```
[-d SETTINGS.DATAPATH] [-fs SETTINGS.FILESPEC] [-o SETTINGS.OUTPUTPATH]
[--pkcs12-passphrase SETTINGS.PKCS12PASSPHRASE]
[--post-export-command SETTINGS.POSTEXPORTCOMMAND]
[-id [SETTINGS.DOMAINS.INCLUDE ...] | -xd [SETTINGS.DOMAINS.EXCLUDE ...]]
```

`SETTINGS.DATAPATH` tells the operator the name of an internal config node; it does not tell
them to type a filesystem path. `SETTINGS.DOMAINS.INCLUDE` actively misleads — the argument
is a space-separated list of domain names, and the metavar reads like a config key to be
supplied verbatim. This was always true, but the story materially raised its exposure: before
this change the usage block was only reached via a deliberate `--help`; now it is printed on
every mistake, which is exactly when an operator is least able to decode plumbing. It is also
the block mirrored into `README.md`, so it is the project's front-page first impression.

**Remedy.** Add `metavar=` to each value-taking argument in `cli_args.py` — `PATH`, `GLOB`,
`PATH`, `RESOLVER_ID`, `PASSPHRASE`, `COMMAND`, `DOMAIN`. `metavar` affects display only; it
changes no flag name, `dest=`, default, or help text, so it is within the story's non-goals.
Regenerate the `README.md` usage block in the same change (see UX-009).

---

### UX-005 — Medium — `README.md` documents neither the new failure mode nor any exit code

**Operator-visible problem.** The story's own "Files in scope" lists `README.md` as
"documents the CLI flag surface; checked for accuracy if unrecognized-arg behavior is now
user-visible". The behaviour *is* now user-visible — it is the headline change — and the
README hunks in `sprint-01.diff` touch only the post-export-command and correlation-id
sections. Nothing anywhere in the README or `docker/README.md` tells an operator that an
unrecognized flag is now fatal, or that it exits `2`. This matters twice over: an operator
upgrading from a prior version gets a container that suddenly refuses to start on an argv
that used to be tolerated, with no changelog line to explain it; and anyone writing a
wrapper script or healthcheck has no documented exit-code contract to branch on — `2` for a
bad flag, `1` for config errors (`require_existing_path`, mutually-exclusive domain lists),
`0` for success — a three-value contract that exists in code and nowhere in the docs.

**Remedy.** Add a short `## Exit codes` section to `README.md` with the three-row table
above, and one sentence under Usage: "An unrecognized or misspelled flag is a fatal error —
the exporter prints usage to stderr and exits 2 rather than ignoring it." Mirror the
upgrade-relevant sentence into `docker/README.md`, where a start-up failure is observed as a
crash-looping container rather than a shell message.

---

### UX-006 — Medium — The active-settings dump is one unwrapped 400-character JSON line

**Operator-visible problem.** `_dump_settings` emits the whole settings object as a single
log record:

```
DEBUG : {"dataPath": "/tmp/uxr/acme", "fileSpec": "*.json", "outputPath": "/tmp/uxr/out", "resolverInPathName": true, ... "appriseUrls": "***REDACTED***"}
```

Fifteen fields on one line, hard-wrapped by whatever terminal the operator happens to have,
with no alignment to scan down. This is the sink the story's second acceptance criterion is
about, and it sits directly beneath `_dump_config`'s confuse output, which *is* pretty-printed
block YAML — so two adjacent dumps of substantially the same data use opposite legibility
conventions, and the better-formatted one is the stale file-config view rather than the
authoritative active-settings view.

**Remedy.** Pretty-print the settings dump: `json.dumps(safe, indent=2, sort_keys=False)`
in `_dump_settings`. If keeping one record per line matters for the JSON console/file
handler (ADR-0023), emit the structure as a log `extra=` field instead of interpolating it
into the message string — the aggregator then gets a real object and the console formatter
can render it indented.

---

### UX-007 — Low — Three sinks, three different redaction markers; the confuse one is ambiguous with a literal value

**Operator-visible problem.** A single DEBUG run shows a redacted value three ways:
`'settings.pkcs12passphrase': '***REDACTED***'` (argparse namespace, Python dict repr),
`pkcs12passphrase: REDACTED` (confuse YAML dump, bare and unquoted), and
`"pkcs12Passphrase": "***REDACTED***"` (settings JSON). The bare `REDACTED` is the problem
one: in a YAML-shaped dump it is syntactically indistinguishable from someone having literally
configured the string `REDACTED` as their passphrase. An operator grepping their logs for
`***REDACTED***` to audit what was masked will silently miss every confuse-sink occurrence.

**Remedy.** `REDACTED` is confuse's own constant and the story is right not to write a second
redactor around it. Instead, make the marker greppable and unambiguous from the outside:
state the convention once in `docs/operational.md` ("a masked value renders as `***REDACTED***`,
or as bare `REDACTED` in the from-file config dump — confuse's own marker"), and add a single
test asserting both spellings are the only two markers any sink emits, so a future sink cannot
introduce a third.

---

### UX-008 — Low — `README.md`'s `--help` mirror has already drifted from the real help text

**Operator-visible problem.** The README reproduces the full `--help` output by hand, and it
is stale: it renders `--restart-container`'s help as "matches the value of the **lable**.
Multiple domains can be **seperated** by ','", while the live `--help` reads "label" and
"separated" — the typos were fixed in `cli_args.py` and never propagated. The install snippet
immediately above is fenced as ` ```basah `. Small, but this block is the project's primary
flag reference and the story touched the CLI's user-visible contract without re-checking it.

**Remedy.** Regenerate the README block from actual output (`COLUMNS=100 traefik-certificate-exporter --help`)
as part of the UX-004 metavar change, and add an assertion to `tests/ci/test_documentation.py`
— which already asserts over doc content — that every long flag in `globalArgParser` appears
in `README.md`, so the two cannot drift silently again.

---

### UX-009 — Low — The one new failure mode is the only output that bypasses the logging contract

**Operator-visible problem.** `parse_args_strict()` runs as `main()`'s first statement, before
`setup_logging()`, so argparse's usage block goes to raw stderr with no level, no timestamp,
no `correlation_id`, and no JSON framing — even when `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEJSON=true`
is set, which the Docker image now exposes specifically so `docker logs` can be shipped to an
aggregator as structured records. An operator who has wired that up sees a crash-looping
container emitting one unparseable multi-line blob, with the actual cause (`unrecognized
arguments: --dtaa-path`) buried in it and invisible to any field-based alert.

The ordering itself is correct and the story's Observability section explicitly accepts it —
structured logging genuinely cannot be configured before argv is parsed. The gap is that the
trade-off is recorded only in the story, not where an operator would find it.

**Remedy.** Document it: one line in `docs/operational.md` next to the correlation-id section
noting that CLI parse failures predate logging configuration and are therefore emitted as
plain text on stderr with exit 2, never as JSON records. No code change warranted.

---

### UX-010 — Low — No `--version`, on a surface operators now see far more often

**Operator-visible problem.** The version is logged once at INFO after a successful start
(`Traefik Certificate Exporter v0.1.3 starting....`), so the only way to learn it is to
successfully start the exporter — which is exactly what an operator *cannot* do when they are
debugging a start-up failure and need to confirm which build is running. `--version` is the
conventional CLI affordance for this and is absent from a usage block that this story has
promoted into the most-seen error surface.

**Remedy.** Add `globalArgParser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")`
in `cli_args.py`. This is an addition to the flag surface rather than a change to an existing
flag, so it brushes the story's non-goals — if that reading is strict, carry it as a follow-up
backlog item rather than folding it into this story's closure.

---

## Non-findings — verified clean

Recorded so closure can rely on them rather than re-testing:

- **Exit code and message on a typo.** `--dtaa-path /tmp` → usage block + `error: unrecognized
  arguments: --dtaa-path /tmp` on stderr, exit `2`. No traceback, no silent ignore. BL-E001-006's
  operator-visible symptom is genuinely gone.
- **`--help` still exits 0** and prints the full option list, confirming the strict parse did not
  break the help path the story flagged as an edge case.
- **No credential leak.** A planted `pkcs12passphrase` (file *and* CLI) and a planted
  `tgram://` Apprise URL appear in zero records of a full DEBUG run across all three sinks.
  BL-E010-003's security obligation holds empirically, as the story claims.
- **No normal-path regression.** A successful `--dry-run` start produces the same INFO sequence
  and exits `0`; the import-time lenient `globalArgs` is untouched, so import-only consumers
  (pytest, REPL, embedding hosts) are unaffected — consistent with the story's reported
  458-passed run.
- **ADR-0025 is faithfully implemented.** Option B as decided: module-level
  `parse_known_args()` retained verbatim, `parse_args_strict()` added alongside, `main()`
  rebinds `globalArgs` as its first statement before any attribute read.

## Assumptions

- Severity is scored by **operator impact**, not fix difficulty, per the rubric in
  `references/validate.md`.
- Findings are confined to UX-bearing acceptance criteria of E011-S01-003. UX-004, UX-007,
  UX-008 and UX-010 describe conditions that predate this story; they are reported because the
  story materially changed how often an operator encounters them, and each remedy is noted
  against the story's stated non-goals so closure can accept or defer deliberately.
- UX-010's remedy adds a flag, which may fall outside this story's non-goals; flagged inline
  as a candidate backlog item rather than a closure blocker.
- No spine pair (`DESIGN.md` / `EXPERIENCE.md`) exists for this project, so the standard
  rubric-walker lens was not dispatched; this single CLI/operator-output lens replaces it.

## Open questions

- None requiring a decision before closure. UX-001 is the only finding a reviewer would argue
  should block sprint acceptance; it is a readability defect inside a working security control,
  not a leak, so it is equally defensible as a fast follow-up.

---

High: 1, Medium: 5, Low: 4
