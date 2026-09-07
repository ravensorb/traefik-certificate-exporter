# ADR-0014: Notifications on `post-export`, delivered by Apprise

- **Status:** Proposed
- **Date:** 2026-09-06
- **Deciders:** Maintainer (ravensorb)
- **Supersedes:** ADR-0013, withdrawn before implementation after an architecture gate
  returned 5 BLOCKER and 13 MAJOR findings
- **Principle(s) in tension:** serving a stated need against designing for needs nobody stated

## Context

The maintainer asked how hard it would be to add webhook support and to look at
pre-export / post-export / cert-export hooks. ADR-0013 answered with an event bus, two consumer
contracts, an optional-extra packaging decision and a configuration redesign — 145–161 hours
and eighteen blocking findings, roughly ten of which existed only because of scope that
document invented. Its postmortem has the breakdown.

This ADR keeps what was asked for and drops what was not.

Today `settings.postexportcommand` runs one subprocess after an export pass
(`libs/post_export.py`, 63 lines): `shlex` parsing, no shell, fixed 30s timeout, exported
domains in `TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS`, dry-run suppression, failures
logged and never allowed to crash the watch loop. It works and is not changing.

## Decision

**1. Add notifications at `post-export` only, delivered by Apprise.**

One new setting alongside `postexportcommand`, taking one or more Apprise destination URLs.
After a pass completes, each is notified with the exported domain list. Delivery is
fire-and-forget: a failure is logged and never propagates, exactly like the existing hook's
non-zero exit.

That single setting covers what the original question actually asked — webhooks — and brings
email, Slack, Discord, ntfy, Gotify, Telegram and Matrix with it at no extra design cost.

**2. Apprise is an ordinary runtime dependency, not an optional extra.**

ADR-0013 made it an extra by analogy with `jsonschema`/`packaging`. The analogy does not hold:
those are optional to keep a *compiled* `rpds-py` chain out of a CI-only validator
(`pyproject.toml` records exactly that reason). Apprise is a user-facing runtime feature and
its chain — `requests` (already a main dependency), `requests-oauthlib`, `click`, `markdown`,
`PyYAML`, `certifi` — is pure Python.

The extra was also unreachable: `docker/Dockerfile` runs `poetry install --only main` with no
`--extras` and no build argument, so the feature could never have been installed in the only
artifact this project ships. Global rule 2 — the constraint was inherited rather than
interrogated, and what it bought was never restated for this case.

**3. No `cert-export`, no `pre-export`, no event bus, no new configuration surface.**

`cert-export` was the single largest complexity driver in ADR-0013 and nobody has asked for
it. `pre-export` is cheap but equally unrequested. Both are easy to add later *because* this
decision keeps the shape flat; neither is added now.

The setting is a list beside the existing keys. **An earlier draft said the existing env
convention addresses it "unchanged"; that was asserted rather than checked, and it is wrong.**
`_parse_domain_list` exists in this repository precisely because confuse does not parse a
comma-separated string into a list, and its own comment says so.

Worse, the comma convention is *unsafe for this value type*: a comma is legal and idiomatic
inside an Apprise URL (`mailto://u:pw@host?to=a@x.com,b@y.com`), so splitting on it fragments
one destination into two malformed ones.

**Resolved by using what confuse already ships.** Indexed environment keys —
`…_APPRISEURLS_0`, `…_APPRISEURLS_1` — yield a real list natively, verified:

```
PROBE_SETTINGS_APPRISEURLS_0=tgram://one
PROBE_SETTINGS_APPRISEURLS_1=slack://two
    →  ['tgram://one', 'slack://two']
```

That is safe for any value, because there is no in-band separator to collide with. No parsing
code is written, the comma convention is explicitly *not* extended to this key, and the
documentation must say which form applies to which setting rather than implying one rule.

**4. Secrets are the one thing this cannot inherit.**

An Apprise URL usually *is* the credential, and `_SECRET_FIELD_PATTERN` in `settings.py`
matches on key *name* — so a value inside a destination list is not reachable by that mechanism
at all, whatever the key is called.

**An earlier draft proposed superseding the key-name mechanism with something of ours. That was
wrong twice over, and the second gate caught it: confuse already ships the answer.** Marking a
config path redacted redacts by *path*, which is exactly the value-shaped case:

```
config['settings']['appriseurls'].redact = True
config.dump(redact=True)        →   appriseurls: REDACTED
```

Verified by running it. Global rule 1 applies to the redactor as much as to the transport, and
writing a second one beside a library facility that already works is what the rule forbids.

**Decision: adopt `confuse`'s `redact`, declare secret-bearing config paths in one registry, and
derive both the redaction and its guard from that registry** rather than from a hand-kept list of
function names. Three sinks must be covered, not the two an earlier draft named — `_dump_settings`,
`_dump_config`, and the raw argparse namespace at `settings.py`, which was leaking
`--pkcs12-passphrase` verbatim and has been fixed as a bug ahead of this work.

**BL-E001-005 is re-scoped, not closed**, and the tracked record is updated in the same change —
prose and machine-readable record disagreeing is how the wrong fix gets implemented.

**5. The Apprise dependency is recorded, not just added.**

| | |
|---|---|
| floor | `^1.9.0` — the first release of the BSD line this project verified |
| licence | **BSD-2-Clause** at 1.13.1; `BSD` at 1.6.0–1.9.x; **MIT** at ≤1.2.x |
| `requires_python` | `>=3.9` at 1.13.1, inside this project's `>=3.10,<3.15` |
| new to the main group | `apprise`, `requests-oauthlib`, `click`, `markdown` — `requests`, `PyYAML` and `certifi` are already `groups = ["main", "dev"]` in `poetry.lock` |

The second gate asserted Apprise was **GPLv3 through 1.8.x**, relicensing at 1.9.0, and treated
that as a copyleft risk for an MIT project shipping an image. **Checked against PyPI, that is
false**: MIT through ~1.2.x, BSD from ~1.6.0 onward, never GPL. The finding was right that the
licence and floor must be recorded; its stated reason was not, and recording the wrong reason
would have been worse than recording nothing.

**6. Delivery carries an explicit timeout.**

`Apprise.notify()` blocks and delivers sequentially, and SMTP can hang for tens of seconds. It
runs on the `threading.Timer` thread inside the drain, so an unbounded call extends the window in
which watch events are being collected rather than processed. *Configurable* timeouts were
deliberately cut from scope; shipping with **no bound at all** is not the same cut, and it would
be a regression against `post_export.py`'s explicit 30 seconds. A fixed delivery timeout is set
and stated here as that file's counterpart.

**7. What a notification means is stated, because the honest answer is not the flattering one.**

Nothing in this codebase detects *change*: every certificate is rewritten on every pass and
`names.append(name)` is unconditional. The image also ships `RUNATSTART=true` alongside
`WATCHFORCHANGES=true`. So a notification means **"an export pass completed"**, not "a
certificate changed" — every container restart and every Traefik write to `acme.json` sends one,
renewal or not. Documented plainly rather than left for an operator to infer after muting the
channel.

## Consequences

- **One story, not an epic.** Estimate to follow from the calibrated estimator.
- **Every blocking gate finding about scope disappears** — they were consequences of
  `cert-export`, the extra, the config redesign and the two-contract split, none of which
  survive here.
- **The two real defects the gate found are already fixed** (`fix(watch):` — the `isWaiting`
  leak and distinct-file loss) and were never dependent on this design.
- **Deferred deliberately, and cheap to revisit:** `pre-export` and `cert-export` consumers,
  a checked HTTP action, and per-event configurable timeouts. Each becomes worth doing when a
  requirement names it. ADR-0013's library survey stands and is the record to consult first.
- **Cost accepted: a failed notification stops nothing.** An operator who needs something to
  *succeed* uses `postexportcommand`, which blocks and reports. The documentation must say so
  plainly rather than let it be discovered during an incident.
