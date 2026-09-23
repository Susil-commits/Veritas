# ADR 001: State Machine Orchestration via Compiled LangGraph

## Status
**Accepted** (2026-09-17)

## Context
Educational dialogue systems require strict pedagogical boundaries. In an unconstrained multi-agent framework (such as raw AutoGen or CrewAI conversational loops), LLMs operate as free-form conversationalists. Under student frustration, adversarial probing, or ambiguity, unconstrained agents frequently default to calculating answers directly or drifting into infinite dialogue loops.

We required an orchestration framework capable of:
1. Enforcing deterministic routing before invoking expensive LLM inference.
2. Intercepting prompt injections, jailbreaks, and distress signals with hard pedagogical redirection.
3. Supporting state persistence and deterministic checkpointing across multi-turn sessions.
4. Guaranteeing cycle detection and bounded recovery pathways when a student is stuck on a misconception.

## Decision
We implemented the core tutoring engine as a compiled **LangGraph state machine** (`backend/graph/orchestrator.py`):

```
       [START]
          │
     ┌────┴────────────────────────┐
     │ (Conditional Safety Check)   │
     ▼                             ▼
[safety_node]                [tutor_node]
 (Deterministic Redirection)   (Socratic Dialogue + CAS Verification)
     │                             │
     ▼                             ▼
   [END]                         [END]
```

Key architectural mechanics:
- **`safety_node`**: Intercepts prompt injections and harmful content prior to tutor generation, guaranteeing zero LLM API token consumption for adversarial inputs.
- **`tutor_node`**: Formulates Socratic guiding inquiries, invokes the deterministic CAS validator to check student candidate equivalence, intercepts accidental answer disclosures, and applies pedagogical attempt-type weighting to Bayesian Knowledge Tracing updates.
- **Strong Typing**: `TutorState` is defined as an explicit `TypedDict` schema tracking session metadata, active misconceptions, problem turns, and cognitive mastery probabilities.

## Consequences

### Positive
- **Deterministic Boundary Guarantees**: Jailbreak attempts are short-circuited before the LLM can generate text, eliminating probabilistic answer leakage.
- **State Machine Explainability**: Every transition, node execution, and thinking step is explicitly logged and exposed in real-time to the frontend thinking trace.
- **Reproducible Testability**: State transitions can be isolated and verified in automated unit tests (`test_startup_smoke.py`) without invoking live API credits.

### Negative / Trade-offs
- Requires formal state schemas and explicit node contracts, introducing slight overhead compared to naive single-prompt completions.
- Dynamic graph topology alterations require recompilation during the application lifespan.
