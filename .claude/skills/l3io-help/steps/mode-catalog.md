# Catalog Mode — list every installed l3io skill and its most-used verbs

Invoked with the `catalog` (or `commands`) argument. Reads
`{project-root}/_bmad/_config/manifest.yaml`, decides which of the four l3io modules are
installed, and prints a compact per-skill table so the user can pick a command without having
to remember which module a skill lives in. Read-only; no state, no config layer, no calibration
model. This is discovery, not recommendation — `steps/step-05-recommend.md` is the "what
should I do next in my current PM state" flow, and stays separate.

## 1. Which modules are installed

For each optional module code, probe the manifest with the pattern from
`references/config-resolution.md` §5:

```bash
grep -qE "^[[:space:]]*-[[:space:]]*name:[[:space:]]*l3io-util[[:space:]]*$" \
  {project-root}/_bmad/_config/manifest.yaml 2>/dev/null && echo "present" || echo "absent"
```

Repeat for `l3io-sec`, `l3io-arch`. `l3io-pm` is present by construction — this skill lives in
it. If the manifest itself is missing, treat every optional module as absent and note it in
the output.

## 2. Emit the catalog

Print one section per **installed** module. Skip an absent module entirely — do not print a
"not installed" row per module, because the point of this mode is a menu the user can pick
from, not an inventory audit.

Column meanings: **verb** is the argument passed to the skill (default = no argument);
**purpose** is when to reach for it. Full flag surface lives in each skill's own SKILL.md and
its reference doc — this mode names the door, it does not carry the room.

### l3io-pm (always present)

| Command | Purpose |
|---|---|
| `/l3io-help` | You're here. Reads state, recommends next action. `progress` for the tree, `list plan` for snapshots, `catalog` for this menu. |
| `/l3io-plan` | Validates readiness, elaborates stories, estimates, and builds the phased execution plan. Use before first execution or when the backlog changes. |
| `/l3io-execute [epic-key]` | Runs the epic + sprint lifecycle: elaboration → dev → review → QA → fix loop → closure. No argument = start next; with an epic key = resume that epic. |
| `/l3io-sync {setup\|push\|pull\|sync\|status}` | Bidirectional sync between l3io-pm state and GitHub Issues. `setup` first, then `sync` for routine use. |
| `/l3io-setup` | Records module settings and registers help entries. Run once per project, or when settings change. |

### l3io-util — only if `l3io-util` is installed

| Command | Purpose |
|---|---|
| `/l3io-doctor` | Health check + ordered fix plan. Default when something feels off. |
| `/l3io-doctor stats` | Plan-aware progress tree. `/l3io-help progress` forwards here. |
| `/l3io-doctor triage` | Reviews open issues, closes what is already fixed, confirms accepted spec departures. |
| `/l3io-doctor migrate-state` | Upgrades legacy state layouts to the sharded tree. Auto-detected; the `check` output tells you if you need it. |
| `/l3io-doctor check-deps` | Confirms which BMad and intra-package skills resolved here. Run after install to verify the environment. |

Additional modes: `check-pm-status`, `migrate-adrs`, `split-status`, `harvest-debt`,
`sort-status`, `update-ai-rules`, `clean-legacy`, `redrive`. Each is documented in
`/l3io-doctor`'s own SKILL.md.

### l3io-sec — only if `l3io-sec` is installed

| Command | Purpose |
|---|---|
| `/l3io-sec-redteam` | Five-lens security analysis (STRIDE, LINDDUN, PASTA, MITRE ATT&CK, CIS) plus AI-poisoning cross-cut. Invoked at epic closure by l3io-execute automatically; run directly for ad-hoc reviews. |

### l3io-arch — only if `l3io-arch` is installed

| Command | Purpose |
|---|---|
| `/l3io-arch-review` | Three modes: **A** design guardrails for a new project, **B** architectural audit of an existing one, **C** decision support with an ADR written on accept. l3io-execute's epic architecture gate uses Mode B automatically; run directly to record an ADR from a design discussion. |

## 3. Closing hint

After the tables, print one line that names the primary flow for a user who has just installed
this extension: `/l3io-setup` first (if not yet configured), then `/l3io-help` (this
skill, no argument) whenever unsure what to do next.

If any optional module was **absent** — record the count in one final sentence, so the user
knows what they could add. Do not list them; the reference doc names them
(`docs/l3io-pm-reference.md`).
