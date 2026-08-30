# Epic 3 / Sprint 1 — Retrospective

## What happened

Both stories done, no carry-over.

- **E003-S01-001** (Fix Domain Include/Exclude Across All Config Surfaces): the real bug
  was not "no mutual-exclusivity check on the config-file/env-var path" as the story
  hypothesized -- it was that `confuse`'s `.get(dict)` on a nested key does not deep-merge
  a partial override with the packaged default's sibling keys. Setting only
  `DOMAINS_INCLUDE` (via env var or config file) silently dropped `domains.exclude`
  entirely, and the filter code's `self.__settings.domains["exclude"]` then raised a
  `KeyError` -- reproduced and confirmed live with `poetry run python3` before writing any
  fix, exactly matching GitHub #5's "have to set EXCLUDE to a dummy value" symptom.
  A second, independent bug in the same area: env vars have no list syntax, so a
  comma-separated `DOMAINS_INCLUDE=foo.com,bar.com` env var was never split into a list at
  all -- confirmed via the same live repro before fixing.
  Fixed by querying `domains.include`/`domains.exclude` as two independent leaf keys
  (which fall back to the default correctly) instead of one combined dict, normalizing
  both env-var strings and real lists through one helper, and adding an explicit
  mutual-exclusivity check that fires regardless of which surface(s) supplied each value.
- **E003-S01-002** (PKCS12 Passphrase CLI flag): straightforward addition following the
  existing `cli_args.py` dest-naming convention; redaction (Epic 1) already covers the new
  flag's dest name (`pkcs12passphrase` matches the existing secret-shaped-key pattern) with
  no code change required.

## Learnings

- A story's stated root cause (written during planning, before the bug was reproduced) can
  be wrong even when the acceptance criteria are right -- always reproduce the reported
  symptom live before writing the fix, not just after.
- `confuse`'s per-source dict merging is shallower than it looks: querying a nested key as
  `dict` returns whichever source's value wins at that exact path, not a recursive merge of
  every source's keys at every depth. Querying leaf keys individually gets confuse's normal
  per-key fallback instead.
- Env vars in this project use a comma-separated convention (documented in
  `docker/README.md` before this session), which `confuse` never parses into a list on its
  own -- `confuse` *does* support real env-var arrays, but only via indexed suffix keys
  (`..._INCLUDE_0`, `..._INCLUDE_1`, ...), a different and incompatible syntax. Switching to
  confuse's native form would be a breaking change for anyone already using commas, so the
  hand-written comma-split was kept deliberately, not because confuse lacks list support
  (an assumption worth double-checking against the library's actual source next time,
  before writing a workaround).
