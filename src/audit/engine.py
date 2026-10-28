"""Audit engine for evaluating contracts against standards using Hybrid Search and Google Gemini."""

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from google.genai import types

from src.audit.client import create_gemini_client, generate_content_with_retry
from src.audit.schemas import (
    ComplianceStatus,
    ConfidenceLevel,
    ContractAuditReport,
)
from src.parsing.document_parser import ContractClause, DocumentParser, ParsedContract
from src.retrieval.hybrid_search import HybridContractRetriever, RubricRetrievalBundle

# Load local .env variables into os.environ
load_dotenv()


class ContractAuditor:
    """Orchestrates hybrid dense+sparse clause retrieval and structured compliance audits using Gemini."""

    def __init__(
        self,
        rubric_path: str | Path = "config/audit_rubric.yaml",
        model_name: str | None = None,
    ):
        """Initialize the auditor with a declarative rubric, hybrid retriever settings, and Gemini client."""
        rubric_file = Path(rubric_path)
        if not rubric_file.exists():
            raise FileNotFoundError(
                f"Rubric configuration not found at: {rubric_file}"
            )

        with open(rubric_file, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

        self.rubric: list[dict[str, Any]] = config_data["rubric"]
        engine_cfg: dict[str, Any] = config_data.get("engine", {})
        retrieval_cfg: dict[str, Any] = engine_cfg.get("retrieval", {})

        # Resolution hierarchy: explicit argument -> env var -> config file -> fallback
        self.model_name = (
            model_name
            or os.environ.get("GEMINI_MODEL")
            or engine_cfg.get("model_name", "gemini-flash-latest")
        )
        self.embedding_model = str(
            engine_cfg.get("embedding_model", "gemini-embedding-001")
        )
        self.temperature = float(engine_cfg.get("temperature", 0.0))

        self.top_k = int(retrieval_cfg.get("top_k", 3))
        self.dense_weight = float(retrieval_cfg.get("dense_weight", 0.5))
        self.sparse_weight = float(retrieval_cfg.get("sparse_weight", 0.5))
        self.rrf_k = int(retrieval_cfg.get("rrf_k", 60))
        self.magic_phrase_boost = float(
            retrieval_cfg.get("magic_phrase_boost", 2.5)
        )
        self.last_retrieval_bundles: list[RubricRetrievalBundle] = []

        self.client = create_gemini_client()

    def _build_system_instruction(self) -> str:
        """Construct the compliance persona and evaluation guardrails."""
        return (
            "You are an expert enterprise legal compliance auditor and procurement specialist.\n"
            "Your objective is to strictly evaluate the submitted contract (or recursive contract hierarchy) "
            "against the provided policy rubric checklist using the hybrid search (dense semantic + sparse "
            "keyword/magic-phrase) retrieved clauses and full contract context.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Grounding: Audit strictly against the facts and clauses in the provided contract documents. "
            "Do not extrapolate or assume unstated terms.\n"
            "2. Hybrid Evidence Priority: Inspect the top retrieved clauses and matched 'magic phrases' "
            "for each rubric item first, then verify against the full contract text.\n"
            "3. Recursive Hierarchy & Order of Precedence (L0 -> L1 -> ... -> Ln):\n"
            "   - Lower level numbers have higher legal precedence (e.g., L0 Addendum overrides L1 SOW, "
            "which overrides L2 Base MSA).\n"
            "   - Override: If a higher-precedence document (L0/L1) amends, replaces, or conflicts with an "
            "ancestor agreement, evaluate compliance based on the governing higher-precedence clause.\n"
            "   - Inheritance: If a higher-precedence document is silent on a topic, recursively inherit the "
            "governing clause from the nearest ancestor agreement (L1, then L2, etc.).\n"
            "   - Silence: Mark an item as 'SILENT' only if it is omitted across the entire hierarchy.\n"
            "4. Status & Alignment Degree Determination:\n"
            "   - 'MET': The governing clause satisfies the policy standard ('ALIGNED_STANDARD') "
            "or acceptable fallback ('ALIGNED_FALLBACK').\n"
            "   - 'DEVIATION': The governing clause addresses the topic but falls short of policy thresholds "
            "('PARTIAL_ALIGNMENT' for minor/negotiable gaps or 'MATERIAL_DEVIATION' for major departures).\n"
            "   - 'SILENT': All documents in the contract hierarchy completely omit the required topic ('SILENT').\n"
            "5. Confidence Level ('HIGH', 'MEDIUM', 'LOW'):\n"
            "   - 'HIGH': Clear, unambiguous contract language (or unambiguous absence) with strong retrieval match "
            "and no unresolved cross-references.\n"
            "   - 'MEDIUM': Clause relies on qualified language, fallback interpretation, or references an external "
            "section/schedule not fully detailed inline.\n"
            "   - 'LOW': Clause is vague, contradictory, depends on missing cross-referenced sections, or "
            "retrieval evidence is weak.\n"
            "6. Grounded Citations: For each item, provide the exact section number (and source document label if "
            "multi-document) plus a verbatim excerpt under 'exact_citation'. If missing across all documents, set "
            "exact_citation to 'Not Found / Silent'.\n"
            "7. Schema Integrity: Ensure compliant_count + deviation_count + silent_count "
            "strictly equals total_items_audited."
        )

    def retrieve_evidence(
        self, clauses: list[ContractClause]
    ) -> list[RubricRetrievalBundle]:
        """Runs hybrid dense + sparse retrieval across contract clauses for all rubric items."""
        retriever = HybridContractRetriever(
            client=getattr(self, "client", None),
            embedding_model=getattr(
                self, "embedding_model", "gemini-embedding-001"
            ),
            top_k=getattr(self, "top_k", 3),
            dense_weight=getattr(self, "dense_weight", 0.5),
            sparse_weight=getattr(self, "sparse_weight", 0.5),
            rrf_k=getattr(self, "rrf_k", 60),
            magic_phrase_boost=getattr(self, "magic_phrase_boost", 2.5),
        )
        bundles = retriever.retrieve_for_rubric(clauses, self.rubric)
        self.last_retrieval_bundles = bundles
        return bundles

    @staticmethod
    def _is_citation_grounded(citation: str, contract_text: str) -> bool:
        """Checks whether the cited quoted snippet or section reference exists in the source contract."""
        norm_contract = re.sub(r"\s+", " ", contract_text.lower()).strip()
        norm_cite = re.sub(r"\s+", " ", citation.lower()).strip()
        if not norm_cite or norm_cite == "not found / silent":
            return False

        # 1. If a quoted excerpt is present, verify that at least one quoted segment appears verbatim
        quote_matches = re.findall(r"[\"'“”‘’]([^\"'“”‘’]{10,})[\"'“”‘’]", citation)
        if quote_matches:
            for q in quote_matches:
                segments = [
                    s.strip(" .,;:")
                    for s in re.split(r"\.{2,}", q.lower())
                    if len(s.strip(" .,;:")) >= 10
                ]
                if segments and any(seg in norm_contract for seg in segments):
                    return True
            return False

        # 2. If 'Section X.Y: <excerpt>' format is used, verify the excerpt appears in the contract
        if ":" in norm_cite:
            after_colon = norm_cite.split(":", 1)[1].strip()
            if len(after_colon) >= 12:
                return after_colon[:30] in norm_contract

        # 3. Bare section reference fallback (ensure not matching a percentage like '99.9%')
        sec_match = re.search(
            r"\b(?:section|article|clause)\s+(\d+(?:\.\d+)?)\b", norm_cite
        )
        if sec_match:
            sec_num = sec_match.group(1)
            if re.search(rf"(?:^|\s){re.escape(sec_num)}(?!\d|%)\b", norm_contract):
                return True

        return norm_cite in norm_contract

    @classmethod
    def verify_and_calibrate_report(
        cls,
        report: ContractAuditReport,
        contract_text: str,
        bundles: list[RubricRetrievalBundle],
    ) -> ContractAuditReport:
        """Calibrates item confidence levels using deterministic citation grounding and retrieval signals."""
        bundle_map = {b.item_id: b for b in bundles}

        for item in report.results:
            bundle = bundle_map.get(item.item_id)

            if item.status == ComplianceStatus.SILENT:
                continue

            # 1. Downgrade to LOW if citation cannot be grounded in the contract text
            if not cls._is_citation_grounded(item.exact_citation, contract_text):
                item.confidence = ConfidenceLevel.LOW
                continue

            # 2. Downgrade to LOW if retriever found zero matching candidate clauses
            if bundle is not None and len(bundle.matches) == 0:
                item.confidence = ConfidenceLevel.LOW
                continue

            # 3. Cap at MEDIUM if matched clause has dangling cross-references to missing sections
            if (
                bundle is not None
                and bundle.missing_cross_references
                and item.confidence == ConfidenceLevel.HIGH
            ):
                item.confidence = ConfidenceLevel.MEDIUM

        return report.recalculate_counts()

    @staticmethod
    def _format_retrieval_evidence(
        bundles: list[RubricRetrievalBundle],
    ) -> str:
        """Formats per-item hybrid search evidence into structured prompt context."""
        lines: list[str] = []
        for bundle in bundles:
            lines.append(f"#### [{bundle.item_id}] {bundle.item_name}")
            if not bundle.matches:
                lines.append(
                    "- No strongly aligned clauses retrieved (potential SILENT topic; verify against full text)."
                )
            else:
                for rank_idx, match in enumerate(bundle.matches, start=1):
                    c = match.clause
                    tag = (
                        "Cross-Referenced Clause"
                        if match.is_cross_reference
                        else f"Candidate #{rank_idx} (RRF={match.rrf_score:.4f}, Dense={match.dense_score:.3f}, Sparse={match.sparse_score:.2f})"
                    )
                    lines.append(
                        f"- **{tag}** | `{c.qualified_id}` ({c.section_heading} - {c.clause_title}):"
                    )
                    if match.matched_magic_phrases:
                        lines.append(
                            f"  - Matched Magic Phrases: {', '.join(repr(p) for p in match.matched_magic_phrases)}"
                        )
                    if match.matched_keywords:
                        lines.append(
                            f"  - Matched Keywords: {', '.join(match.matched_keywords)}"
                        )
                    lines.append(f"  - Excerpt: {c.text}")
            if bundle.missing_cross_references:
                lines.append(
                    f"- **Warning (Dangling Cross-Reference):** Clause references {', '.join(bundle.missing_cross_references)} which is not present in the contract hierarchy."
                )
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _format_hierarchy_summary(parsed_contract: ParsedContract | None) -> str:
        """Formats the recursive governing hierarchy chain (L0 -> L1 -> ... -> Ln) when multi-document."""
        if parsed_contract is None:
            return ""
        chain = parsed_contract.iter_hierarchy()
        if len(chain) <= 1:
            return ""
        chain_lines = [
            "### CONTRACT GOVERNING HIERARCHY (ORDER OF PRECEDENCE: L0 OVERRIDES L1, L1 OVERRIDES L2, ETC.):"
        ]
        for level, node in enumerate(chain):
            label = node.document_label or Path(node.file_name).stem
            chain_lines.append(
                f"- **Level L{level}**: `{label}` (`{node.file_name}`)"
            )
        return "\n".join(chain_lines) + "\n\n"

    def audit_contract(
        self,
        contract_text: str,
        contract_title: str,
        vendor_name: str,
        parsed_contract: ParsedContract | None = None,
    ) -> ContractAuditReport:
        """Chunk contract(s), execute hybrid dense+sparse search, and run Gemini compliance evaluation."""
        if parsed_contract is not None and parsed_contract.clauses:
            clauses = parsed_contract.resolve_hierarchical_clauses()
            effective_contract_text = parsed_contract.compile_hierarchical_text()
        else:
            clauses = DocumentParser().chunk_clauses(
                contract_text.replace("\r\n", "\n").strip()
            )
            effective_contract_text = contract_text

        retrieval_bundles = self.retrieve_evidence(clauses)
        formatted_evidence = self._format_retrieval_evidence(retrieval_bundles)
        hierarchy_summary = self._format_hierarchy_summary(parsed_contract)
        num_items = len(self.rubric)

        user_prompt = f"""
### COMPLIANCE AUDIT RUBRIC ({num_items} MANDATORY ITEMS):
{json.dumps(self.rubric, indent=2)}

{hierarchy_summary}### HYBRID SEARCH RETRIEVED EVIDENCE (DENSE SEMANTIC + SPARSE MAGIC-PHRASE FUSION):
{formatted_evidence}

### INBOUND VENDOR CONTRACT TEXT:
Contract Title: {contract_title}
Vendor: {vendor_name}

{effective_contract_text}

---
Perform the compliance evaluation for all {num_items} items in the rubric.
Generate the complete audit assessment conforming strictly to the requested schema, including status, alignment_degree, and confidence for each item.
"""

        # Enforce structured output via Gemini's native Pydantic schema configuration
        config = types.GenerateContentConfig(
            system_instruction=self._build_system_instruction(),
            temperature=self.temperature,
            response_mime_type="application/json",
            response_schema=ContractAuditReport,
        )

        response = generate_content_with_retry(
            client=self.client,
            model=self.model_name,
            contents=[user_prompt],
            config=config,
        )

        if not response.text:
            raise ValueError(
                "Gemini API returned an empty text payload during contract audit evaluation."
            )

        # Parse, validate, and calibrate confidence levels against contract grounding
        report = ContractAuditReport.model_validate_json(response.text)
        return self.verify_and_calibrate_report(
            report=report,
            contract_text=effective_contract_text,
            bundles=retrieval_bundles,
        )
