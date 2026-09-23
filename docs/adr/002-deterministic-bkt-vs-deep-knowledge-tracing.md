# ADR 002: Deterministic Bayesian Knowledge Tracing (BKT) vs. Deep Knowledge Tracing (DKT)

## Status
**Accepted** (2026-09-17)

## Context
A central requirement of Veritas is tracking latent student mastery across 10 Common Core State Standards (CCSS) to drive adaptive remediation and provide transparent radar charts for parents and educators.

In modern educational data mining, two primary paradigms exist:
1. **Deep Knowledge Tracing (DKT)**: Utilizing recurrent neural networks (RNNs/LSTMs) or Transformers to predict future student response probabilities from sequence embeddings.
2. **Bayesian Knowledge Tracing (BKT)**: A calibrated Hidden Markov Model (HMM) tracking binary latent knowledge states parameterized by Prior $P(L_0)$, Learn Rate $P(T)$, Guess Rate $P(G)$, and Slip Rate $P(S)$.

## Decision
We chose **Bayesian Knowledge Tracing (BKT)** calibrated via bounded Maximum Likelihood Estimation (MLE) over empirical ASSISTments benchmark datasets, augmented with two cognitive extensions:
1. **Pedagogical Attempt-Type Scaffolding Weighting**: Differentiating between unassisted independent discovery, hinted attempts, and corrections made after Socratic scaffolding.
2. **Ebbinghaus Memory Retention Decay**: Modeling exponential forgetting across unpracticed intervals:
   $$P(L_{t+\Delta t}) = P_{prior} + (P(L_t) - P_{prior}) \cdot e^{-\lambda \cdot \Delta t}$$
3. **Prerequisite Knowledge DAG**: Structuring skills in a Directed Acyclic Graph to enable recursive root-deficit diagnosis when a student struggles with higher-order concepts.

## Rationales & Comparisons

| Metric | Bayesian Knowledge Tracing (BKT) | Deep Knowledge Tracing (DKT) |
| :--- | :--- | :--- |
| **Explainability** | High: Each parameter ($P(L), P(T), P(G), P(S)$) has direct psychological meaning for parents/teachers. | Low: Black-box latent weights impossible to explain to non-technical guardians. |
| **Cold-Start Efficiency** | Immediate: Operates robustly with 0–1 interactions using empirical priors. | Poor: Requires long interaction sequences before embeddings stabilize. |
| **Compute / Latency** | $< 0.1\text{ms}$ execution in pure Python arithmetic on Edge/FastAPI. | Requires PyTorch/ONNX runtime inference ($10–50\text{ms}$, heavy container size). |
| **Auditability & Compliance**| 100% deterministic calculations; transparently auditable under EdTech standards. | Susceptible to unexpected neural drift and hallucinations. |

## Consequences

### Positive
- Parents and educators can inspect exact probabilities on the CCSS Mastery Radar chart with complete mathematical trust.
- Instant, zero-latency mastery state updates without GPU infrastructure or bulky machine learning model runtimes.
- Bounded MLE calibration prevents catastrophic runaway scores.

### Negative / Trade-offs
- Standard BKT assumes a single skill per problem. We mitigate this through composite utility weighting and prerequisite DAG traversals during RAG problem selection.
