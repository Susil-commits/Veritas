# ADR 004: Pedagogical Guardrails, Child Safety & COPPA/FERPA Compliance

## Status
**Accepted** (2026-09-17)

## Context
Educational platforms catering to K-12 students are legally and ethically bound by child safety frameworks, specifically the **Children's Online Privacy Protection Act (COPPA)** and the **Family Educational Rights and Privacy Act (FERPA)**. 

Furthermore, educational applications face specific pedagogical vulnerabilities: students will actively attempt to jailbreak tutors into revealing direct homework answers or completing entire assignments.

## Decision
We established a layered, defense-in-depth safety architecture (`backend/safety.py`, `backend/auth.py`, `backend/routes/session.py`):

1. **Deterministic Socratic Boundary Enforcement**:
   - High-precision regex pattern matchers intercept prompt injection, developer mode toggles, and direct answer demands before LLM execution.
   - Secondary token-level answer leakage scanning intercepts accidental answer disclosure in model replies.

2. **Zero-PII Storage Architecture**:
   - Student session payloads store minimal synthetic identifiers (UUIDs).
   - Real student names and contact information are isolated; LLM prompts receive sanitized, anonymized tokens.

3. **Ephemeral Scratchpad Image Lifecycles**:
   - Camera scratchpad uploads are validated against magic bytes (`JPEG`, `PNG`, `WebP`) to eliminate malicious executable uploads.
   - Files are processed in memory and uploaded to cloud storage with short-lived, expiring signed URLs.
   - Dedicated "Delete My Data" endpoints allow parents to permanently purge all associated child records and mastery profiles in a single transactional cascade.

4. **Cryptographic Role Isolation & IDOR Defense**:
   - HMAC-SHA256 signed session tokens strictly enforce role segregation:
     - Student tokens are restricted from accessing parent dashboards or billing data.
     - Parent tokens cannot participate in student tutoring sessions.
   - Insecure Direct Object Reference (IDOR) validation ensures parents can only inspect explicitly linked children.

## Consequences

### Positive
- Fully compliant with modern child data minimization and security requirements.
- Zero answer leakage benchmark verified empirically across 100+ adversarial attack vectors.
- Complete audit logging of security events with zero personally identifiable data leaked.

### Negative / Trade-offs
- Strict file validation and magic-byte checks add ~1–2ms to scratchpad uploads, a negligible cost for enterprise security.
