# 📋 Enterprise Contract Compliance Audit Engine

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg?logo=python)](https://www.python.org/)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2.6+-e92063.svg?logo=pydantic)](https://docs.pydantic.dev/)
[![Gemini API](https://img.shields.io/badge/Google--GenAI-2.20+-orange.svg)](https://ai.google.dev/)
[![Package Manager](https://img.shields.io/badge/uv-Fast%20Packaging-purple.svg)](https://docs.astral.sh/uv/)
[![Testing](https://img.shields.io/badge/Pytest-Passing-brightgreen.svg?logo=pytest)](https://pytest.org/)

An automated document intelligence engine designed to audit inbound vendor technology agreements against enterprise procurement policies. Powered by Hybrid Search (Dense Semantic + Sparse BM25 & Legal "Magic Phrase" Matching), Google Gemini, and Pydantic v2 structured decoding, the system converts unstructured legal text into a standardized compliance intake matrix complete with clause citations, alignment degrees, and calibrated confidence ratings (`HIGH`, `MEDIUM`, `LOW`).

---

## 📌 Business Context & The Operational Challenge

In enterprise procurement and legal operations, reviewing inbound vendor paper is an expensive, high-friction bottleneck:
* **Operational Inefficiency:** Manual review across 10–40 compliance checkpoints requires 2–4 hours per contract, slowing vendor onboarding and service delivery.
* **Reviewer Inconsistency:** Subjective interpretations between negotiators lead to inconsistent contract quality, missed boilerplate deviations, and silent non-compliance.
* **Asymmetric Risk Exposure:** Overlooking subtle contractual traps (e.g., narrow 15-day auto-renewal notice windows, missing transition assistance, or uncapped consequential damages) exposes organizations to severe downstream operational and financial liabilities.

### The Solution
This engine transforms manual review into an automated, deterministic audit (< 2 minutes per contract):
1. Ingests, normalizes, and chunks multi-format contracts (`.md`, `.txt`, `.docx`) into hierarchical `ContractClause` units while preserving inline tables and cross-references.
2. Executes **Hybrid Dense + Sparse Retrieval** per standard component—fusing semantic embeddings (`gemini-embedding-001`) with Okapi BM25 lexical matching and exact contractual "magic phrase" boosting via Reciprocal Rank Fusion (RRF).
3. Uses Gemini's constrained JSON generation (with exponential backoff retry) to extract itemized verdicts (`MET`, `DEVIATION`, `SILENT`), granular alignment degrees (`ALIGNED_STANDARD`, `ALIGNED_FALLBACK`, `PARTIAL_ALIGNMENT`, `MATERIAL_DEVIATION`, `SILENT`), and calibrated confidence levels (`HIGH`, `MEDIUM`, `LOW`) alongside verbatim clause citations.
4. Auto-generates stakeholder deliverables: human-readable Markdown sheets, formatted Microsoft Word (`.docx`) intake assessments, and an append-only CSV audit ledger.

---

## 🏗 System Architecture

```text
                [ Inbound Contract (.md / .docx / .txt) ]
                                   │
                                   ▼
               [ Clause-Aware DocumentParser & Chunker ]
               - Preserves reading order of paragraphs & tables
               - Segments into hierarchical ContractClause chunks
               - Extracts section cross-references (e.g. Section 9)
                                   │
                                   ▼
            [ Hybrid Dense + Sparse Clause Search Engine ]
            - Dense: Gemini Semantic Embeddings (Cosine Sim)
            - Sparse: Okapi BM25 + Legal "Magic Phrase" Boost
            - Fusion: Reciprocal Rank Fusion (RRF) + Cross-Refs
                                   │
                                   ▼
                   [ Google Gemini Audit Engine ]
                    - Model: gemini-flash-latest (Temp: 0.0)
                    - Exponential Backoff API Retry (client.py)
                    - Constrained JSON Schema Decoding
                                   │
                                   ▼
          [ Pydantic v2 Validation & Grounding Calibration ]
            - Post-validation count & alignment synchronization
            - Verbatim quote grounding & confidence calibration
                                   │
          ┌────────────────────────┼────────────────────────┐
          ▼                        ▼                        ▼
[ Markdown Report ]     [ Word (.docx) Sheet ]   [ Compliance Ledger ]
(reports/audit_results) (reports/audit_results)  (reports/compliance_scorecard.csv)
```

## 🛡 Key Technical Innovations & Guardrails
1. **Clause-Level Structural Chunking & Hybrid Dense + Sparse Search**

    Contracts often hinge on specific terms of art ("magic words" like `"commercially reasonable efforts"`, `"indemnify, defend, and hold harmless"`, or `"without cause"`).
    * `DocumentParser.chunk_clauses()` segments agreements into `ContractClause` objects with parent section headers, sentence-aligned overlap for oversized clauses, inline `.docx` table order preservation (`iter_inner_content()`), and automatic cross-reference extraction.
    * `HybridContractRetriever` combines dense semantic embeddings (`gemini-embedding-001` with an offline character/word n-gram TF-IDF vector fallback) and sparse lexical scoring (Okapi BM25 with legal stem normalization + exact `magic_phrases` boosting) using Reciprocal Rank Fusion (RRF):

    $$\text{RRF}(c) = \frac{w\text{ (dense)}}{k + \text{rank(dense, } c\text{)}} + \frac{w\text{ (sparse)}}{k + \text{rank(sparse, } c\text{)}} + \text{MagicBoost}(c)$$

2. **Declarative Policy & Search Decoupling**  

    Business requirements, fallback tolerances, retrieval weights, domain `keywords`, and legal `magic_phrases` are decoupled from Python application code in `config/audit_rubric.yaml`. Procurement teams can update SLA baselines, renewal windows, or search phrases without modifying the core parsing or inference modules.

3. **Eliminating Arithmetic Hallucination Drift & Calibrating Confidence**

    Large language models can suffer from internal counting drift when generating structured JSON arrays. `ContractAuditReport.recalculate_counts()` (triggered via `@model_validator(mode="after")`) dynamically computes all status and confidence counts (`high_confidence_count`, `medium_confidence_count`, `low_confidence_count`) directly from the validated `results` list:

    $$\text{CompliantCount} = \sum [r.\text{status} == \text{MET}]$$

    $$\text{DeviationCount} = \sum [r.\text{status} == \text{DEVIATION}]$$

    $$\text{SilentCount} = \sum [r.\text{status} == \text{SILENT}]$$

    Furthermore, `ContractAuditor.verify_and_calibrate_report()` performs deterministic post-validation checks:
    * **Citation Grounding (`_is_citation_grounded`):** Verifies that quoted excerpts or section references exist in the contract text; ungrounded citations are automatically downgraded to `LOW` confidence.
    * **Dangling Cross-Reference Calibration:** When a matched clause depends on a cross-referenced section omitted from the contract (e.g., `"Section 9"` referenced in Section 11.2), confidence is capped at `MEDIUM`.

4. **Explicit "Absence as an Insight" (Handling Silence)**

    In standard RAG search, an unmentioned topic yields poor retrieval or hallucinated boilerplate. In this compliance engine, silence is an explicit contractual finding:
    * If an agreement omits Termination for Convenience or Indemnification, the model flags the item as `SILENT` (`AlignmentDegree.SILENT`) and records the citation as `"Not Found / Silent"`.

## 🛠 Tech Stack
* Language & Runtime: Python 3.11+
* Environment & Package Management: uv (`pyproject.toml` + `uv.lock`)
* LLM & Embedding Engine: Google Gemini (`google-genai>=2.20.0`)
* Schema Validation: `pydantic>=2.6.0` (Native JSON schema enforcement)
* Configuration: PyYAML (`config/audit_rubric.yaml`)
* Document Processing & Reporting: `python-docx>=1.1.0`
* Testing & Quality Assurance: Pytest, Pytest-Mock, Ruff, Mypy

## 📂 Repository Topology

```text
contract-compliance-auditor/
├── .github/
│   └── workflows/
│       └── ci.yml                 # Automated Ruff, Mypy, and Pytest CI pipeline
├── config/
│   └── audit_rubric.yaml          # Declarative 10-item policy standards & search phrases
├── data/
│   ├── raw_contracts/             # Test & inbound contracts (.md, .docx)
│   ├── golden_benchmarks/         # Ground-truth evaluation contracts
│   └── guidance_standards/        # Enterprise procurement standard documentation
├── reports/
│   ├── audit_results/             # Output Markdown & Word audit reports (.gitignored)
│   └── compliance_scorecard.csv   # Historical audit tracking ledger (.gitignored)
├── src/
│   ├── __init__.py
│   ├── run_audit.py               # Pipeline CLI entry point
│   ├── parsing/
│   │   ├── __init__.py
│   │   └── document_parser.py     # Ingestion, normalization & clause-level chunking
│   ├── retrieval/
│   │   ├── __init__.py
│   │   └── hybrid_search.py       # Dense + Sparse (BM25 + Magic Phrase) RRF retriever
│   ├── audit/
│   │   ├── __init__.py
│   │   ├── client.py              # Resilient Gemini client & exponential backoff retry
│   │   ├── schemas.py             # Pydantic v2 schemas, alignment & confidence models
│   │   └── engine.py              # Hybrid audit orchestrator & grounding calibration
│   └── formatting/
│       ├── __init__.py
│       └── reporter.py            # Markdown and Word (.docx) document renderers
├── tests/
│   ├── __init__.py
│   ├── test_parser.py             # Ingestion, DOCX order & clause chunking unit tests
│   ├── test_hybrid_search.py      # Dense, sparse, magic-phrase & cross-ref search tests
│   ├── test_schemas.py            # Pydantic validation & confidence sync unit tests
│   └── test_audit_engine.py       # Offline mock pipeline, calibration & live API tests
├── pyproject.toml                 # uv-managed dependencies and tool configurations
├── uv.lock                        # Pinned deterministic dependency graph
└── README.md
```

## 🚀 Quickstart Guide
1. **Prerequisites & Environment Setup**

    Clone the repository and initialize the virtual environment using `uv`:
    ```bash
    git clone https://github.com/YOUR_USERNAME/contract-compliance-auditor.git
    cd contract-compliance-auditor
    uv sync --extra dev
    ```

2. **Configure Credentials**

    Create a `.env` file in the project root containing your Gemini API key:
    ```toml
    GEMINI_API_KEY="your-actual-api-key-here"
    ```

3. **Run Automated Tests & Static Analysis**

    ```bash
    # Run offline unit, hybrid search, and schema tests
    uv run pytest tests/ -k "not test_live_gemini" -v

    # Run the full suite including live Gemini API integration
    uv run pytest tests/test_audit_engine.py -v

    # Run Ruff linter and Mypy type checker
    uv run ruff check .
    uv run mypy src tests
    ```

4. **Execute Contract Compliance Audit**

    ```bash
    uv run python -m src.run_audit --contract data/raw_contracts/generic_tech_vendor_contract.md --title "Apex Cloud MSA" --vendor "Apex Cloud Technologies, LLC"
    ```

## 📊 Sample Audit Output

When evaluated against the synthetic test contract (`generic_tech_vendor_contract.md`), the engine outputs the following itemized audit review:

| Item # | Focus Area | Policy Baseline Standard | Identified Vendor Term | Audit Verdict & Alignment | Confidence | Verbatim Citation / Section |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **REQ-01** | Service Level Agreement (SLA) | >= 99.9% availability commitment (commercially reasonable efforts acceptable) | Vendor commits to commercially reasonable efforts to maintain at least 99.9% System Availability per calendar month. | ✅ MET (`ALIGNED_STANDARD`) | 🟢 HIGH | Section 8.1: Vendor will use commercially reasonable efforts to ensure the SaaS Services maintain an operational System Availability of at least ninety-nine and nine-tenths percent (99.9%) during each calendar month, excluding scheduled maintenance. |
| **REQ-02** | SLA Service Credits | >= 10% monthly credit per 0.5% outage or escalating fee credit schedule | No financial remedy or service credit mechanism is provided for downtime or failure to meet availability targets. | ❌ SILENT (`SILENT`) | 🟢 HIGH | Not Found / Silent |
| **REQ-03** | Auto-Renewal Notice Window | >= 60 days prior notice (acceptable fallback: 45-60 days prior notice) | Non-renewal notice must be delivered at least 15 days prior to term expiration. | ⚠️ DEVIATION (`MATERIAL_DEVIATION`) | 🟢 HIGH | Section 5.1: This Agreement shall automatically renew for additional successive twelve (12) month periods unless either party delivers written notice of non-renewal at least fifteen (15) days prior to the expiration of the current Term. |
| **REQ-04** | Termination for Convenience | Permitted with <= 30 days written notice (acceptable fallback: <= 60 days, zero penalty) | The contract only permits termination for cause under material breach; termination for convenience is omitted. | ❌ SILENT (`SILENT`) | 🟢 HIGH | Not Found / Silent |
| **REQ-05** | Termination Assistance / Transition | 60 days support, no additional fee (acceptable fallback: 30 days support at standard T&M rates) | Customer is granted 14 days to self-export data using native tools, after which data may be permanently deleted. | ⚠️ DEVIATION (`PARTIAL_ALIGNMENT`) | 🟢 HIGH | Section 5.3: Customer shall have fourteen (14) days to self-export Customer Data using native tools, after which Vendor may permanently delete all stored records. |
| **REQ-06** | Payment Terms | Net 60 days (acceptable fallback: Net 45 days) | Payment is required within 30 calendar days from the invoice date, billed annually in advance. | ⚠️ DEVIATION (`PARTIAL_ALIGNMENT`) | 🟢 HIGH | Section 3.2: All undisputed fees shall be invoiced annually in advance. Invoices are payable within thirty (30) calendar days from the date of the invoice. |
| **REQ-07** | Price Escalation Cap | <= 3% or CPI annually (acceptable fallback: <= 5% flat cap annually) | Vendor reserves the right to increase annual subscription fees by up to 7.0%. | ⚠️ DEVIATION (`MATERIAL_DEVIATION`) | 🟢 HIGH | Section 3.3: Upon the conclusion of the Initial Term or any Renewal Term, Vendor reserves the right to increase annual subscription fees by up to seven percent (7.0%) upon forty-five (45) days prior written notice. |
| **REQ-08** | Mutual Indemnification | Uncapped IP infringement and data protection indemnity (acceptable fallback: Capped at 3x annual contract value) | The agreement contains no indemnification clause protecting Customer against third-party intellectual property infringement or data breaches. | ❌ SILENT (`SILENT`) | 🟢 HIGH | Not Found / Silent |
| **REQ-09** | Limitation of Liability Cap | 1x to 2x aggregate annual fees mutual liability threshold (acceptable fallback: Fees paid in preceding 12 months) | Vendor's liability is capped at fees paid in the preceding 12 months (meets fallback scale; unilateral cap with missing Section 9 cross-reference). | ✅ MET (`ALIGNED_FALLBACK`) | 🟡 MEDIUM | Section 11.2: EXCEPT FOR BREACHES OF CONFIDENTIALITY UNDER SECTION 9, VENDOR'S TOTAL AGGREGATE LIABILITY ARISING OUT OF OR RELATED TO THIS AGREEMENT SHALL BE LIMITED STRICTLY TO THE FEES ACTUALLY PAID BY CUSTOMER IN THE TWELVE (12) MONTHS PRECEDING THE CLAIM. |
| **REQ-10** | Governing Law & Jurisdiction | State of Delaware or New York (acceptable fallback: State of Customer headquarters) | Governed by Delaware law with personal jurisdiction in Delaware courts. | ✅ MET (`ALIGNED_STANDARD`) | 🟢 HIGH | Section 14.1: This Agreement and any dispute arising hereunder shall be governed by, and construed in accordance with, the laws of the State of Delaware, without regard to its conflict of law principles. Both parties consent to personal jurisdiction within Delaware courts. |

**Summary Scorecard**
* Total Audited: 10
* Compliant (MET): 3 (30.0%) — 2 `ALIGNED_STANDARD`, 1 `ALIGNED_FALLBACK`
* Deviations (DEVIATION): 4 (40.0%)
* Silent / Missing Terms (SILENT): 3 (30.0%)
* Confidence Distribution: 9 HIGH | 1 MEDIUM | 0 LOW
* Overall Risk Assessment: CRITICAL (due to missing indemnification and convenience termination)

All results are automatically persisted to `reports/audit_results/` as both interactive Markdown and styled Word documents, with high-level KPIs logged to `reports/compliance_scorecard.csv`.
