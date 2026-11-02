# Autonomous Multi-Agent Lead Generation System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an extensible, multi-agent lead intelligence system engineered to discover, verify, score, and craft bespoke web-scraping outreach for B2B agencies, powered by a multi-key AI router (5x Groq + 5x Gemini).

**Architecture:** Orchestrator-Workers Architecture with task-based AI routing, deterministic verification, explainable 100-point buyer scoring, browserless HTTP agency website intelligence, and an in-context reinforcement memory loop.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLAlchemy 2.0 / SQLite, Groq SDK, Google-GenAI SDK, HTTPX, BeautifulSoup4, dnspython, phonenumbers, RapidFuzz, Pandas, OpenPyXL, FastAPI.

**Spec:** `GEMINI.md`

## Global Constraints
- Strictly zero-trust: Unknown fields must remain `null` or `unknown`. Agents are penalized for inventing data.
- Never guarantee email deliverability from MX records alone; MX validity yields `likely_valid`, never `verified`.
- Browserless first: Use HTTPX, curl_cffi, BeautifulSoup4, and JSON-LD/meta parsing instead of heavy headless browsers wherever possible.
- Multi-key rotation: Support 5 Groq keys and 5 Gemini keys with automatic cooldown state machine on 429 and rate-limiting.
- Outreach drafts must be strictly < 75 words, plain-text, zero initial links, value-first custom scraping offer, and status `draft`.

## Review Focus
1. Rate limit (429) on one Groq or Gemini key rotates to the next key without failing the pipeline.
2. Agency classification rejects B2C / non-ICP businesses with explicit `rejection_reason`.
3. Founder/Owner name requires verifiable URL and text snippet in `evidence`.
4. Outreach generator connects agency's actual client vertical with a concrete scraping hook and sample dataset offer.
5. All 10 acceptance criteria from Section 10 of GEMINI.md pass automated tests.

---

## Phase Breakdown

### Phase 1: Core Configuration, Schemas & Multi-Key AI Router
**Files:**
- Create: `config/settings.py`
- Create: `config/sources_catalog.yaml`
- Create: `core/schemas.py`
- Create: `core/llm_router.py`
- Test: `tests/test_phase1_router.py`

- [x] Task 1.1: Build `config/settings.py` to parse 5 Gemini keys (`GEMINI_API_KEY_1..5`) and 5 Groq keys (`GROQ_API_KEY_1..5`), scoring thresholds, and ICP settings.
- [x] Task 1.2: Build `config/sources_catalog.yaml` defining adapter metadata and rate limits.
- [x] Task 1.3: Build `core/schemas.py` with standard Pydantic v2 models (`LeadRecord`, `AgencyType`, `VerificationStatus`, `PriorityTier`, `CampaignPlan`).
- [x] Task 1.4: Build `core/llm_router.py` with multi-key pool, round-robin rotation, 429 cooldown state machine, token tracker, and structured JSON generation.
- [x] Task 1.5: Run tests in `tests/test_phase1_router.py` verifying Groq & Gemini multi-key rotation and structured output.

### Phase 2: Database Persistence & Storage Layer
**Files:**
- Create: `core/database.py`
- Test: `tests/test_phase2_database.py`

- [x] Task 2.1: Implement SQLAlchemy models for `leads`, `duplicate_groups`, `campaigns`, `feedback_memory`, and `golden_examples`.
- [x] Task 2.2: Add repository CRUD operations with session management.
- [x] Task 2.3: Test database schema creation and lead record persistence.

### Phase 3: Multi-Source Discovery Adapters
**Files:**
- Create: `adapters/base.py`
- Create: `adapters/search_api_adapter.py`
- Create: `adapters/google_maps_adapter.py`
- Create: `adapters/directory_adapter.py`
- Test: `tests/test_phase3_adapters.py`

- [x] Task 3.1: Define abstract `SourceAdapter` base class.
- [x] Task 3.2: Implement `SearchApiAdapter` using DuckDuckGo search API with high-intent footprints.
- [x] Task 3.3: Implement `GoogleMapsAdapter` for local B2B agency queries.
- [x] Task 3.4: Implement `DirectoryAdapter` for public B2B agency directories.
- [x] Task 3.5: Test multi-source discovery results and output formatting.

### Phase 4: High-Speed Agency Website Recon & Intelligence (Browserless)
**Files:**
- Create: `adapters/website_enrichment.py`
- Test: `tests/test_phase4_website_enrichment.py`

- [x] Task 4.1: Build HTTP harvester using `httpx` to crawl homepage, `/about`, `/team`, `/services`, `/case-studies`.
- [x] Task 4.2: Extract JSON-LD, meta tags, and clean text.
- [x] Task 4.3: Integrate with `LLMRouter` to extract 4 critical scraping signals: Agency Niche Specialization, Service Delivery Model, Case Studies/Proof, and Team/Decision-Maker footprints with evidence quotes.
- [x] Task 4.4: Test website enrichment against mock and real agency pages.

### Phase 5: Normalization, Deduplication & Deterministic Verification
**Files:**
- Create: `pipeline/normalizer.py`
- Create: `pipeline/deduplicator.py`
- Create: `pipeline/verifier.py`
- Test: `tests/test_phase5_pipeline.py`

- [x] Task 5.1: Build `normalizer.py` for root domains, phone E.164, and agency clean names.
- [x] Task 5.2: Build `deduplicator.py` for exact domain/phone match and fuzzy RapidFuzz similarity merging.
- [x] Task 5.3: Build `verifier.py` for DNS/MX checks (`dnspython`), syntax validation, personal vs role email discrimination, and founder evidence verification.
- [x] Task 5.4: Test normalization, deduplication merging, and verification logic.

### Phase 6: 100-Point Scraping-Buyer Scorer & Outreach Agent
**Files:**
- Create: `pipeline/scorer.py`
- Create: `pipeline/outreach_agent.py`
- Test: `tests/test_phase6_scorer_outreach.py`

- [x] Task 6.1: Implement explainable 100-point scoring formula ($S_{\text{opp}} = S_{\text{icp}} + S_{\text{data\_need}} + S_{\text{niche}} + S_{\text{contact}} + S_{\text{dm}} + S_{\text{fresh}}$) and separate Factual Confidence ($C_{\text{fact}}$).
- [x] Task 6.2: Implement `outreach_agent.py` generating value-first custom scraping pitch (<75 words, sample data offer, no links).
- [x] Task 6.3: Test scoring weights, threshold tier classification, and outreach drafts.

### Phase 7: Self-Improving Learning Loop (Rewards & Mistake Memory)
**Files:**
- Create: `learning/evaluator.py`
- Create: `learning/memory_store.py`
- Test: `tests/test_phase7_learning.py`

- [x] Task 7.1: Implement `memory_store.py` for storing penalties (mistakes to avoid) and rewards (golden examples).
- [x] Task 7.2: Inject golden examples and mistake guardrails dynamically into LLM prompts.
- [x] Task 7.3: Implement `evaluator.py` for tracking accuracy, latency, and Cost Per Qualified Lead (CPQL).
- [x] Task 7.4: Test memory feedback injection and evaluation metrics.

### Phase 8: Master Orchestrator (Campaign DAG & Quality Gate)
**Files:**
- Create: `core/orchestrator.py`
- Test: `tests/test_phase8_orchestrator.py`

- [x] Task 8.1: Implement natural language campaign parser (extracts agency type, geography, niche, lead quantity).
- [x] Task 8.2: Build asynchronous execution DAG coordinating adapters -> enrichment -> verification -> deduplication -> scoring -> outreach.
- [x] Task 8.3: Enforce zero-trust quality gate and budget guards.
- [x] Task 8.4: Test end-to-end campaign execution.

### Phase 9: FastAPI Dashboard & Exporters
**Files:**
- Create: `api/main.py`
- Create: `api/exporter.py`
- Test: `tests/test_phase9_api.py`

- [x] Task 9.1: Build FastAPI endpoints for creating campaigns, viewing leads, approving/rejecting drafts.
- [x] Task 9.2: Build CSV and XLSX export functionality with custom formatting.
- [x] Task 9.3: Test API endpoints and file export outputs.

### Phase 10: Complete Verification Against GEMINI.md Acceptance Criteria
**Files:**
- Create: `tests/eval_dataset.json`
- Create: `tests/test_acceptance_criteria.py`

- [x] Task 10.1: Run benchmark evaluation against all 10 criteria from Section 10 of GEMINI.md.
- [x] Task 10.2: Generate final validation report.
