"""Unit tests for the hybrid (dense semantic + sparse BM25/magic-phrase) search engine."""

from pathlib import Path
from unittest.mock import MagicMock

import yaml

from src.parsing.document_parser import DocumentParser
from src.retrieval.hybrid_search import HybridContractRetriever


def _load_rubric() -> list[dict]:
    with open("config/audit_rubric.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["rubric"]


def test_hybrid_search_matches_expected_clauses_and_magic_phrases():
    """Verify hybrid search ranks the best-suited contract clause #1 for each standard component."""
    parser = DocumentParser()
    parsed = parser.parse(Path("data/raw_contracts/generic_tech_vendor_contract.md"))
    rubric = _load_rubric()

    retriever = HybridContractRetriever(client=None, top_k=3)
    bundles = retriever.retrieve_for_rubric(parsed.clauses, rubric)
    bundle_map = {b.item_id: b for b in bundles}

    # REQ-01 (SLA) -> Section 8.1 with magic phrase "commercially reasonable efforts"
    req01 = bundle_map["REQ-01"]
    assert req01.matches[0].clause.clause_id == "Section 8.1"
    assert "commercially reasonable efforts" in req01.matches[0].matched_magic_phrases
    assert "system availability" in req01.matches[0].matched_magic_phrases

    # REQ-03 (Auto-Renewal Notice Window) -> Section 5.1
    req03 = bundle_map["REQ-03"]
    assert req03.matches[0].clause.clause_id == "Section 5.1"
    assert "automatically renew" in req03.matches[0].matched_magic_phrases
    assert "written notice of non-renewal" in req03.matches[0].matched_magic_phrases

    # REQ-04 (Termination for Convenience) -> Retrieves Section 5.2 (Termination for Cause)
    req04 = bundle_map["REQ-04"]
    assert req04.matches[0].clause.clause_id == "Section 5.2"
    assert "termination for cause" in req04.matches[0].matched_magic_phrases
    assert "terminate for convenience" not in req04.matches[0].matched_magic_phrases

    # REQ-05 (Termination Assistance) -> Section 5.3
    req05 = bundle_map["REQ-05"]
    assert req05.matches[0].clause.clause_id == "Section 5.3"
    assert "self-export customer data" in req05.matches[0].matched_magic_phrases

    # REQ-06 (Payment Terms) -> Section 3.2
    req06 = bundle_map["REQ-06"]
    assert req06.matches[0].clause.clause_id == "Section 3.2"
    assert "thirty (30) calendar days" in req06.matches[0].matched_magic_phrases

    # REQ-07 (Price Escalation Cap) -> Section 3.3
    req07 = bundle_map["REQ-07"]
    assert req07.matches[0].clause.clause_id == "Section 3.3"
    assert "seven percent (7.0%)" in req07.matches[0].matched_magic_phrases

    # REQ-09 (Limitation of Liability) -> Section 11.2 & missing cross-ref to Section 9
    req09 = bundle_map["REQ-09"]
    top_ids_09 = [m.clause.clause_id for m in req09.matches]
    assert "Section 11.2" in top_ids_09[:2]
    assert "Section 11.1" in top_ids_09[:2]
    assert "Section 9" in req09.missing_cross_references

    # REQ-10 (Governing Law) -> Section 14.1
    req10 = bundle_map["REQ-10"]
    assert req10.matches[0].clause.clause_id == "Section 14.1"
    assert "laws of the state of delaware" in req10.matches[0].matched_magic_phrases


def test_hybrid_search_expands_present_cross_references():
    """Verify that when a matched clause references another existing section, it is attached."""
    contract_text = """
## Section 9: Confidentiality
9.1 Confidentiality Obligations. Each party shall safeguard Confidential Information with strict care.

## Section 11: Limitation of Liability
11.2 Liability Ceiling. EXCEPT FOR BREACHES UNDER SECTION 9, LIABILITY IS LIMITED TO 12 MONTHS FEES.
"""
    parsed = DocumentParser().parse_text(contract_text)
    rubric_item = [
        {
            "id": "REQ-09",
            "name": "Limitation of Liability Cap",
            "description": "Aggregate liability cap.",
            "target_value": "1x annual fees",
            "keywords": ["liability", "ceiling"],
            "magic_phrases": ["liability ceiling"],
        }
    ]

    retriever = HybridContractRetriever(client=None, top_k=1)
    bundles = retriever.retrieve_for_rubric(parsed.clauses, rubric_item)
    assert len(bundles) == 1
    bundle = bundles[0]

    assert bundle.matches[0].clause.clause_id == "Section 11.2"
    assert bundle.missing_cross_references == []
    cross_refs = [m for m in bundle.matches if m.is_cross_reference]
    assert len(cross_refs) == 1
    assert cross_refs[0].clause.clause_id == "Section 9.1"


def test_hybrid_search_uses_gemini_dense_embeddings_when_available():
    """Verify dense cosine similarity fusion when Gemini embed_content returns float vectors."""
    contract_text = """
## Section 1: Payment
1.1 Invoicing. Customer pays invoices within 45 days.

## Section 2: Governing Law
2.1 Venue. Governed by New York law.
"""
    parsed = DocumentParser().parse_text(contract_text)
    rubric = [
        {
            "id": "REQ-10",
            "name": "Governing Law",
            "description": "Governing jurisdiction",
            "target_value": "New York",
            "keywords": [],
            "magic_phrases": [],
        }
    ]

    # 2 clauses + 1 rubric query = 3 embeddings
    mock_client = MagicMock()
    emb_clause_1 = MagicMock(values=[1.0, 0.0, 0.0])
    emb_clause_2 = MagicMock(values=[0.0, 1.0, 0.0])
    emb_query = MagicMock(values=[0.0, 0.99, 0.01])
    mock_client.models.embed_content.return_value = MagicMock(
        embeddings=[emb_clause_1, emb_clause_2, emb_query]
    )

    retriever = HybridContractRetriever(client=mock_client, top_k=2)
    bundles = retriever.retrieve_for_rubric(parsed.clauses, rubric)

    mock_client.models.embed_content.assert_called_once()
    assert bundles[0].matches[0].clause.clause_id == "Section 2.1"
    assert bundles[0].matches[0].dense_rank == 1
    assert bundles[0].matches[0].dense_score > 0.99


def test_hybrid_search_recursive_three_tier_hierarchy_inheritance_and_override():
    """Verify hybrid search resolves overrides, amendments, and inherited clauses across L0 -> L1 -> L2."""
    msa_text = """
## Section 5: Term and Termination
5.1 Auto-Renewal. Agreement automatically renews unless written notice of non-renewal is given 15 days prior.

## Section 9: Confidentiality
9.1 Obligations. Both parties shall keep Confidential Information strictly confidential.

## Section 11: Limitation of Liability
11.2 Liability Ceiling. EXCEPT FOR BREACHES OF CONFIDENTIALITY UNDER SECTION 9, TOTAL AGGREGATE LIABILITY IS LIMITED TO FEES ACTUALLY PAID IN THE PRECEDING 12 MONTHS.

## Section 14: General Provisions
14.1 Governing Law. Governed by the laws of the State of Delaware.
"""
    sow_text = """
## Section 3: Fees and Payment
3.2 Invoicing Schedule. Invoices are payable within thirty (30) calendar days from the date of the invoice.

## Section 8: Service Levels
8.1 Uptime Commitment. Vendor will use commercially reasonable efforts to maintain System Availability of 99.9% each calendar month.
"""
    addendum_text = """
## Section 1: Amendments to SOW and MSA
1.1 Renewal Window Amendment. Section 5.1 of the MSA is hereby amended to require sixty (60) days prior written notice.
3.2 Payment Terms Override. Notwithstanding Section 3.2 of the SOW, all undisputed fees under this Addendum are payable Net 60 days from the date of the invoice.
"""

    parser = DocumentParser()
    hierarchy = parser.parse_text_hierarchy(
        [
            ("Addendum", addendum_text),
            ("SOW", sow_text),
            ("MSA", msa_text),
        ]
    )
    clauses = hierarchy.resolve_hierarchical_clauses()
    rubric = _load_rubric()

    retriever = HybridContractRetriever(client=None, top_k=3)
    bundles = retriever.retrieve_for_rubric(clauses, rubric)
    bundle_map = {b.item_id: b for b in bundles}

    # REQ-06 (Payment Terms): L0 Addendum override ranks #1 ahead of L1 SOW
    req06_ids = [m.clause.qualified_id for m in bundle_map["REQ-06"].matches]
    assert req06_ids[0] == "[Addendum (L0)] Section 3.2"
    assert "[SOW (L1)] Section 3.2" in req06_ids
    assert "notwithstanding" in bundle_map["REQ-06"].matches[0].matched_magic_phrases

    # REQ-03 (Auto-Renewal): L0 Addendum Section 1.1 (amending Section 5.1) and L2 MSA Section 5.1 are both surfaced
    req03_ids = [m.clause.qualified_id for m in bundle_map["REQ-03"].matches]
    assert "[Addendum (L0)] Section 1.1" in req03_ids
    assert "[MSA (L2)] Section 5.1" in req03_ids

    # REQ-01 (SLA): Inherited from L1 SOW Section 8.1
    assert bundle_map["REQ-01"].matches[0].clause.qualified_id == "[SOW (L1)] Section 8.1"

    # REQ-09 (Liability Cap): Inherited from L2 MSA Section 11.2, with Section 9 resolved in L2 MSA
    req09 = bundle_map["REQ-09"]
    assert req09.missing_cross_references == []
    req09_ids = [m.clause.qualified_id for m in req09.matches]
    assert "[MSA (L2)] Section 11.2" in req09_ids
    assert "[MSA (L2)] Section 9.1" in req09_ids

    # REQ-10 (Governing Law): Inherited from L2 MSA Section 14.1
    assert bundle_map["REQ-10"].matches[0].clause.qualified_id == "[MSA (L2)] Section 14.1"
