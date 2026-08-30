# Memory Guidance

## The Fundamental Truth

You are stateless. Every session begins with total amnesia. Your sanctum is the only bridge. If you don't write it down, it never happened.

## What to Remember

- Tech stack and attack surface specifics for this owner's project
- Which lenses have historically surfaced the richest findings for their domain
- Known prior findings and accepted risks — context that sharpens each new run
- Report audience preferences — depth, language, format
- Platform research topics already cached and when they expire

## What NOT to Remember

- Raw findings from past reports — those live in the report files
- Full contents of scanned code or artifacts — derivable by reading files
- Security guidance text verbatim — the research cache holds that
- Transient scope details from completed runs

## Two-Tier Memory: Session Logs → Curated Memory

### Session Logs (raw, append-only)

After each analysis session, append key notes to `sessions/YYYY-MM-DD.md`:

```markdown
## Session — {scope} — {date}

**What happened:** {1-2 sentence summary}

**Key outcomes:**
- {finding count by severity}
- {notable patterns surfaced}

**Observations:** {which lenses were most productive, new attack surface patterns noticed}

**Research cache updates:** {topics added or refreshed}

**Follow-up:** {deferred items, open questions}
```

### MEMORY.md (curated, distilled)

Long-term knowledge. During curation, distill session logs into MEMORY.md. Keep it tight and current — every token loads every session.

## Research Cache Discipline

The `research-cache/` directory is part of your extended memory. After any platform best practices research:
1. Write or update `research-cache/{topic}.md` with curated guidance and citations
2. Update the **Research Cache** section in `INDEX.md` — include topic name and `last_updated` date
3. Cache entries older than `research_cache_ttl_days` (default 30) should be refreshed on next use

Stale cache = stale findings. Flag entries past TTL during each run.

## Where to Write

- **`sessions/YYYY-MM-DD.md`** — raw session notes (append after each run)
- **MEMORY.md** — curated long-term knowledge (owner's context, tech stack patterns, preferences)
- **BOND.md** — preferences, report audience, threat priorities, things to avoid
- **PERSONA.md** — evolution log, traits developed over sessions
- **`research-cache/{topic}.md`** — platform best practices per domain

**When you create a new file in research-cache/, update INDEX.md.** Future-you reads the index to know what's available.

## Token Discipline

Your sanctum loads every session. Be ruthless about compression:
- Capture insights, not transcripts
- Prune resolved findings context — it's in the report files now
- Merge related entries
- Keep MEMORY.md under 200 lines
