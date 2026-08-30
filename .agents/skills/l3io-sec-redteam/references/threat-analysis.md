# Threat Analysis

## What Success Looks Like

Findings across all applicable lenses, each with:
- **Title** — specific, descriptive, not generic ("Unauthenticated admin endpoint at /api/admin/users", not "Missing authentication")
- **Attack path** — concrete reproduction steps from an adversary's perspective
- **Impact** — what an adversary gains; who is affected; what data or systems are at risk
- **Recommendation** — specific code or design change, not generic advice
- **Lens** — which perspective surfaced it (may span multiple)

A clean report on non-trivial scope is a failure of analysis. If no Critical or High findings surface, re-examine with a fresh angle before declaring the scope clean.

## The Five Lenses

### 1 — External Attacker

Adversary with no privileged access, attacking from outside. Check:
- Injection points: SQL, command, LDAP, template, path traversal, deserialization
- Authentication bypass: weak tokens, predictable resets, missing auth on sensitive routes
- Authorization gaps: IDOR, missing ownership checks, horizontal/vertical privilege escalation
- Data exfiltration: verbose errors revealing internals, unprotected sensitive fields, improper export controls
- API abuse: undocumented endpoints, rate limit bypass, parameter tampering, mass assignment
- Client-side: XSS, CSRF, open redirects, insecure storage in browser/local state

**AI poisoning cross-cut:** Prompt injection from external input → model manipulation. Indirect injection via content the model processes (documents, emails, web pages). Output handling vulnerabilities — where model output reaches code execution or privileged operations.

### 2 — Malicious Insider

Adversary with legitimate but limited access, attacking from inside. Check:
- Privilege abuse: accessing data beyond their role; using elevated permissions for unauthorized purposes
- Out-of-scope data access: querying other tenants' or users' data; abusing bulk export or reporting features
- Audit gap exploitation: operations that succeed without leaving audit trails; log tampering; bypassing monitoring
- Corruption and deletion: overwriting others' data; injecting malicious content into shared state
- Supply chain injection: inserting malicious code or data via legitimate contribution paths

**AI poisoning cross-cut:** Training data poisoning via insider write access to data pipelines. Backdoors planted in model training or fine-tuning workflows. Exfiltration of proprietary prompts, training data, or model artifacts.

### 3 — Chaos Engineer

Adversary who doesn't attack the happy path — they attack failure modes. Check:
- Failure propagation: what happens when a downstream service fails mid-transaction? Does the system leave partial state?
- Partial-write corruption: failed writes that commit some changes but not others; orphaned records; inconsistent state
- Race conditions and TOCTOU: check-then-act patterns; concurrent modifications to shared state; non-atomic operations
- Resource exhaustion: unbounded loops, large input processing, memory leaks under load, connection pool exhaustion
- Non-idempotent retries: operations that succeed twice causing double-charges, duplicate records, or repeated side effects
- Recovery path security: does error handling restore security invariants? Does cleanup code skip access checks?

**AI poisoning cross-cut:** Model degradation under adversarial input distribution shift. Inference behavior under resource pressure. Recovery behavior when the AI component fails mid-request.

### 4 — Abusive Legitimate User

Adversary who uses the system exactly as designed, but in ways designers didn't intend. Check:
- Feature misuse: scraping, automated bulk operations, feature chaining to escalate access
- Logic flaws: operating steps out of expected order; triggering transitions the state machine allows but shouldn't
- Edge inputs: zero values, null/empty, maximum values, negative numbers, unicode edge cases, encoding attacks
- Shared state corruption: inputs that corrupt other users' experiences; per-tenant resource consumption affecting other tenants
- Boundary conditions: behavior at exact limits (max file size, max items, expiry boundaries)

**AI poisoning cross-cut:** Adversarial prompts crafted by legitimate users. Jailbreaking through legitimate-looking inputs. Systematic probing of model behavior to identify exploitable patterns.

### 5 — Design and Architecture Red Team

System-level weaknesses not visible at the code level. Check:
- Missing controls: security controls specified in architecture but absent in implementation
- Trust boundary violations: components communicating over boundaries without authentication or validation
- Defense-in-depth gaps: single points of failure in security controls; no fallback if one layer fails
- Observability gaps: security-relevant events that aren't logged; no alerting on anomalous patterns
- Recovery capability: what happens after a breach? Are there kill switches, revocation mechanisms, audit trails adequate for forensics?
- Secrets exposure: hardcoded credentials, keys in config, secrets in version control or logs

## HALT Conditions

**Empty scope** — no artifacts, no entry points identified: halt and ask for clarification before running any lens.

**Zero Critical/High on non-trivial scope** — if the scope contains auth code, data access patterns, or external interfaces and zero Critical/High findings surface: mandatory re-analysis. Choose a different angle, assume a different attacker model, examine from the chaos engineer lens if not done thoroughly. Document why the score is genuinely low before declaring the scope clean.

**Auth code with no auth findings** — if the scope includes authentication, authorization, or identity management code and zero auth findings surface: re-examine ownership checks, token validation, and privilege escalation paths explicitly. Document your reasoning.
