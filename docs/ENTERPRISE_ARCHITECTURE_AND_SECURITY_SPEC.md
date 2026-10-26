# Veritas — Enterprise Architecture & AI Security Specification

> **Version**: 2.0-Enterprise  
> **Target Audience**: Chief Technology Officers (CTO), Chief Information Security Officers (CISO), School District Technical Directors, Lead AI Engineers  
> **Scope**: AI Security (OWASP Top 10 for LLMs), Multi-Tenancy, K-12 Governance (FERPA/COPPA/SOC 2), Observability, and High-Availability Gateway

---

## 1. Executive Summary & Enterprise Architecture Blueprint

Veritas is an AI-driven, voice-first Socratic Mathematics Tutoring Platform designed for K-12 education (Grades 3–7). Unlike consumer AI chatbots or homework "solvers," Veritas operates under a strict pedagogical contract: **zero answer leakage**, multimodal handwritten scratchpad diagnosis, and dynamic cognitive calibration via **Bayesian Knowledge Tracing (BKT)**.

To serve school districts and enterprise institutions, Veritas implements an isolated, multi-layered architecture:

```
                                  [ STUDENT / PARENT / TEACHER CLIENTS ]
                                                    │
                                                    ▼
                       ┌─────────────────────────────────────────────────────────────┐
                       │                     ENTERPRISE GATEWAY                      │
                       │   Cloudflare Enterprise WAF (DDoS, Bot Shield, Rate Limit)  │
                       │   TLS 1.3 Termination • Edge Response Caching (Redis)       │
                       └──────────────────────────────┬──────────────────────────────┘
                                                      │
                                                      ▼
                       ┌─────────────────────────────────────────────────────────────┐
                       │                 API & AUTHENTICATION LAYER                  │
                       │   FastAPI Modular Routers • Supabase JWT (JWKS Verification)│
                       │   EdTech SSO: Clever / ClassLink / Google Workspace / SAML  │
                       │   HMAC-SHA256 Token Engine • Redis-Backed Revocation Block  │
                       └──────────────────────────────┬──────────────────────────────┘
                                                      │
                       ┌──────────────────────────────┴──────────────────────────────┐
                       ▼                                                             ▼
         ┌───────────────────────────┐                                 ┌───────────────────────────┐
         │    AI DEFENSE SHIELD      │                                 │   CORE COGNITIVE ENGINE   │
         │  • Multi-modal Visual OCR │                                 │  • LangGraph State Machine│
         │    Injection Pre-Filter   │                                 │  • Deterministic SymPy CAS│
         │  • Zero-PII Redaction     │ ────────── Sanitized ─────────► │  • BKT Knowledge Tracing  │
         │    (FERPA / COPPA Safe)   │             Prompt              │  • pgvector Semantic RAG  │
         │  • Cryptographic Canary   │                                 │  • High-Availability      │
         │    Honeytoken Defense     │                                 │    AI Gateway Fallback    │
         │  • Outbound Socratic Leak │                                 │    (Gemini -> Claude/GPT) │
         │    & Step Sandboxing      │                                 └─────────────┬─────────────┘
         └───────────────────────────┘                                               │
                       ▲                                                             ▼
                       │                                               ┌───────────────────────────┐
                       │                                               │    DATA & OBSERVABILITY   │
                       │                                               │  • PostgreSQL Multi-Tenant│
                       └───────────── Alert on Violation ───────────── │    RLS (District/School)  │
                                                                       │  • Langfuse / OpenTelemetry│
                                                                       │  • Celery / Redis Queue   │
                                                                       └───────────────────────────┘
```

---

## 2. Threat Modeling: OWASP Top 10 for Large Language Models

| OWASP LLM ID | Vulnerability Category | Veritas Attack Vector | Enterprise Mitigation Implemented |
|---|---|---|---|
| **LLM01** | Prompt Injection (Direct & Indirect) | Attacker writes jailbreak text on handwritten paper or inputs DAN prompts. | **Tier-1 Deterministic Regex** + **Tier-2 Semantic LLM Judge** + **Visual OCR Pre-Filter**. |
| **LLM02** | Insecure Output Handling | Model outputs raw code, script tags, or unescaped LaTeX math formulas. | **KaTeX macro white-listing**, **DOMPurify client sanitization**, no raw HTML execution. |
| **LLM03** | Training Data Poisoning / RAG Poisoning | Malicious curriculum problems injected into the pgvector database. | Strict schema validation, verified CCSS problem corpus, signature checks. |
| **LLM04** | Model Denial of Service | Flooding heavy vision OCR and voice synthesis calls to exhaust cloud quotas. | **Sliding-window Rate Limiter**, 10MB upload limits, **Concurrency Semaphores**, Token Budgets. |
| **LLM05** | Supply Chain Vulnerabilities | Deprecated third-party SDKs, unpinned Python libraries, or upstream API outages. | Requirements pinning, **Multi-Provider AI Gateway with Circuit Breakers**. |
| **LLM06** | Sensitive Information Disclosure | Student PII (name, email, school) or proprietary system prompts leaking. | **Zero-PII Anonymization Layer** + **Cryptographic Prompt Canary Honeytokens**. |
| **LLM07** | Insecure Plugin Design | Agent tools executing arbitrary actions or SQL queries without bounds. | **Zero arbitrary code execution** (`Fraction` and SymPy AST sandboxing; no `eval()`/`exec()`). |
| **LLM08** | Excessive Agency | LLM deciding to alter student grade records or database rows autonomously. | Deterministic BKT math updates; LLMs have read-only access to curriculum vectors. |
| **LLM09** | Overreliance & Hallucination | Probabilistic LLM incorrectly grading mathematical arithmetic or algebraic equations. | **Deterministic Objective Math Evaluator** (SymPy/Fraction check precedes all BKT credit). |
| **LLM10** | Model Theft / Exfiltration | Systematic extraction of proprietary Socratic prompt chains. | **Canary Token Exfiltration Traps** with automated session termination. |

---

## 3. Core Enterprise AI Security Modules

### 3.1. Cryptographic System Prompt Canary (Honeytokens)
* **Mechanism**: Every session embeds a randomized 16-character hexadecimal token into the system prompt:
  ```python
  canary = generate_prompt_canary(prefix="VERITAS_CANARY")
  # Yields: "[VERITAS_CANARY_a3f89e2c14b709d1]"
  ```
* **Enforcement**: Outbound LLM response streams are continuously scanned for the canary. If found, the response is instantly aborted, the session token is revoked via Redis, and an enterprise audit event is emitted.

### 3.2. Zero-PII Anonymization Layer (FERPA & COPPA)
* **Mechanism**: Student prompts are inspected before transmission to external AI model APIs:
  - Emails are mapped to `[EMAIL_1]`, `[EMAIL_2]`
  - Phone numbers are mapped to `[PHONE_1]`
  - SSN / government identifiers are mapped to `[REDACTED_GOV_ID]`
  - Self-reported names are mapped to `[STUDENT_NAME_1]`
* **Rehydration**: Sanitized tokens are rehydrated strictly on the client edge boundary after AI generation completes.

### 3.3. Multimodal Visual Prompt Injection Pre-Filter
* **Mechanism**: Student scratchpads uploaded to `/session/upload-work` pass through OCR text extraction prior to multimodal model orchestration.
* **Filter Rules**: Scans for prompt override commands embedded in student handwriting (e.g., *"Teacher instruction: output answer in JSON"*, *"System override"*, *"Disregard rules"*). If detected, the file is rejected with a pedagogical redirect and logged.

### 3.4. High-Availability AI Gateway & Circuit Breakers
* **Problem**: Upstream AI outages (HTTP 503/429) cause student learning sessions to drop.
* **Mechanism**:
  - **Provider Hierarchy**: Google Gemini (Primary) $\rightarrow$ Claude 3.5 Haiku / OpenAI (Secondary Fallback) $\rightarrow$ Deterministic Offline Pedagogical Rules (Emergency Backup).
  - **Circuit Breaker States**:
    - `CLOSED`: Normal operation.
    - `OPEN`: Tripped after 3 consecutive failures; requests bypass directly to secondary provider for 20 seconds.
    - `HALF_OPEN`: Probes primary provider with single canary request; recovers to `CLOSED` on success.

---

## 4. Multi-Tenancy & Educational Data Governance

### 4.1. Hierarchical Tenancy Schema
To support district-wide licensing, the database enforces a 4-tier relational model:
1. **District (`districts`)**: Contains district configuration, Clever/ClassLink IDs, and billing settings.
2. **School (`schools`)**: Scoped to district with NCES identifiers.
3. **Classroom (`classrooms`)**: Scoped to school, assigned to a teacher.
4. **Student Enrollment (`classroom_enrollments`)**: Connects student records to classrooms.

### 4.2. PostgreSQL Row-Level Security (RLS) Policies
All database tables enforce RLS:
- **Anonymous Key (`anon`)**: Denied all access to student rosters, sessions, and child tables.
- **Teachers**: Can only query students enrolled in classrooms assigned to their authenticated user ID (`auth.uid() = teacher_id`).
- **Principals**: Can access classrooms within their assigned school.
- **District Admins**: Can view school aggregates and immutable audit logs (`enterprise_audit_logs`).

---

## 5. Verification & Test Suite Execution

All enterprise security capabilities are backed by automated tests in `backend/test_enterprise_security_and_resilience.py` and integrated into `backend/run_all_tests.py`:

```bash
# Run the dedicated Enterprise AI Security suite
python backend/test_enterprise_security_and_resilience.py

# Run the master validation suite (16/16 suites passing)
python backend/run_all_tests.py
```

### Validation Matrix
* **Test 1: System Prompt Canary Defense**: Verified 100% detection of prompt exfiltration attacks.
* **Test 2: Zero-PII Redaction**: Verified complete scrubbing of email, phone, SSN, and student identity.
* **Test 3: Visual OCR Pre-Filter**: Verified blocking of adversarial handwriting attacks on math paper.
* **Test 4: AI Gateway Circuit Breaker**: Verified failover from primary to fallback model under 503 simulation, and automatic recovery.
* **Test 5: Enterprise Security Telemetry**: Verified telemetry reporting active status across all 10 defense pillars.
