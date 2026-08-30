# Scope and Surface Mapping

## What Success Looks Like

A surface map covering:
1. **Entry points** — all external interfaces: APIs, webhooks, UI inputs, scheduled triggers, message queues, file ingestion
2. **Trust boundaries** — where the system trusts data it shouldn't; where elevated privileges are granted; where internal services call each other without verification
3. **Data flows** — input → processing → storage → output paths; where sensitive data (PII, tokens, keys, financial data) travels and where it rests
4. **Auth checkpoints** — where identity is verified; where it's assumed without verification; where access control decisions are made
5. **Persistent state** — databases, caches, queues, files, logs — anything that can be corrupted, exfiltrated, or manipulated out of band
6. **AI/ML components** — model inputs, training data pipelines, inference endpoints, output handling — if present

The surface map is internal scaffolding, not a report deliverable. It drives which attack paths are realistic in subsequent analysis. A scope with no entry points or no trust boundaries is incomplete — expand until the picture is coherent.

## Your Approach

Read the target artifacts — source files, architecture docs, story File Lists, API definitions. Build the map from what's actually implemented, not from documentation assumptions. An undocumented endpoint is still an entry point. An implicit trust relationship is still a boundary.

If scope is vague (e.g. "this epic's output") — trace the codebase changes listed in story File Lists to identify what was introduced or modified.

**Halt if scope is empty:** If no artifacts can be located or the scope is too vague to identify any entry points, halt immediately. Do not run analysis on an undefined surface — ask for clarification.

## After Mapping

Confirm internally: does this surface make sense for the stated scope? A sprint with 3 stories modifying a single API should produce a small, focused map. An epic-level analysis should produce a broader picture. Gaps in the map are as important as what's in it.
