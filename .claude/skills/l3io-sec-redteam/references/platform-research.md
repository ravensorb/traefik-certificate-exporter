# Platform Best Practices Research

## What Success Looks Like

For each cloud or platform service present in the analysis scope, either:
- A finding citing a specific authoritative guidance doc (with link) where a violation exists, OR
- An explicit confirmation of compliance with a citation (if the implementation matches current guidance)

Guidance must be current. Stale citations from outdated docs are worse than no citations — they create false confidence.

Source neutrality: prefer the official documentation for whatever cloud, platform, or framework is in scope (AWS docs, Google Cloud docs, Azure docs, Kubernetes docs, OWASP, CIS Benchmarks, NIST, vendor security baselines). Do not privilege any single vendor.

## Cache Protocol

### Before Searching

1. Read `INDEX.md` from sanctum — check the **Research Cache** section for available topics and `last_updated` dates
2. Identify which topics are relevant to the current scope (identity, networking, storage, compute, AI/ML, container/orchestration, etc.)
3. For each relevant topic:
   - If cache entry exists AND age ≤ `research_cache_ttl_days`: load from `research-cache/{topic}.md` — no web search needed
   - If cache entry is missing or stale: run WebSearch (see below), then write back to cache

**Stale entries**: if `last_updated` date is more than `research_cache_ttl_days` ago, treat as stale and refresh.

### Running Live Research

For each topic requiring live research, identify the platforms/services in scope and search for current authoritative guidance. Examples:
- `{platform} {topic} security best practices`
- `{platform} {service} security baseline`
- CIS Benchmark / OWASP / NIST guidance for the relevant service
- The official documentation for the framework or service in scope

Curate the relevant findings — do not dump raw search results. Extract the specific practices, the rationale, and the documentation links.

### Writing Cache Entries

After live research, write or update `{sanctum}/research-cache/{topic}.md`:

```markdown
---
topic: {topic-name}
last_updated: {YYYY-MM-DD}
---

# {Topic Name} — Platform Best Practices

## Key Security Requirements
{Curated list of practices relevant to the platforms in scope}

## Common Violations
{What teams typically get wrong, with specific guidance links}

## Citations
{Authoritative source URLs with titles}
```

Then update the **Research Cache** section in `INDEX.md`:
```
- `research-cache/{topic}.md` — last_updated: {YYYY-MM-DD}
```

## Topic Coverage

Cache topics are created on demand for whatever platforms appear in scope. Examples:
- `identity` — IAM/RBAC, federation, conditional access, managed identities, OAuth/OIDC
- `networking` — segmentation, private endpoints, ingress/egress controls, service mesh
- `storage` — encryption at rest/in transit, access controls, retention, signed URLs
- `compute` — host hardening, container/image security, serverless runtime security
- `ai-ml` — responsible AI, model access controls, training data governance, output safety
- `secrets` — secret stores, rotation, just-in-time access
- `observability` — security event logging, alerting, audit trails

Add new topic files on demand when the scope introduces a service or platform not yet cached.

## After Research

Add platform best practices findings to the report alongside findings from the threat analysis lenses. Group them under a "Platform Best Practices" section or fold them into the relevant lens section when they directly support a lens finding.
