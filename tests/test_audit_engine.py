"""Automated unit and integration test suite for the contract compliance engine."""

import json
import os
from pathlib import Path

import pytest

from src.audit.engine import ContractAuditor
from src.audit.schemas import (
    AlignmentDegree,
    ComplianceStatus,
    ConfidenceLevel,
    ContractAuditReport,
    RiskCriticality,
)
from src.formatting.reporter import (
    render_compliance_docx,
    render_compliance_markdown,
)
from src.parsing.document_parser import DocumentParser
from src.run_audit import append_scorecard_csv, slugify_title

# Ground-truth synthetic contract representing 7 evaluated items and 3 omitted (silent) items
SYNTHETIC_CONTRACT_TEXT = """
# Master Cloud Services Agreement (MSA)
Vendor: Apex Cloud Technologies, LLC ("Vendor")
Client: Enterprise Purchasing Corp ("Customer")
Effective Date: March 1, 2026

## Section 3: Fees, Invoicing, and Payment
3.2 Invoicing Schedule. Invoices are payable within thirty (30) calendar days from the date of invoice.
3.3 Fee Adjustments. Vendor reserves the right to increase annual subscription fees by up to seven percent (7.0%).

## Section 5: Term, Renewals, and Termination
5.1 Term and Auto-Renewal. Automatically renews unless written notice is delivered at least fifteen (15) days prior.
5.2 Termination for Cause. Either party may terminate immediately upon 30 days notice of material breach.
5.3 Effect of Termination. Customer shall have fourteen (14) days to self-export Customer Data.

## Section 8: Service Availability & Warranties
8.1 Uptime Commitment. Maintain an operational System Availability of at least ninety-nine and nine-tenths percent (99.9%).

## Section 11: Limitation of Liability
11.2 Liability Ceiling. Total aggregate liability limited strictly to fees actually paid by Customer in the twelve (12) months preceding the claim.

## Section 14: General Provisions
14.1 Governing Law. Governed by the laws of the State of Delaware.
"""

# Ground-truth expected audit result payload for mocking
MOCK_AUDIT_PAYLOAD = {
    "contract_title": "Apex Cloud MSA",
    "vendor_name": "Apex Cloud Technologies, LLC",
    "total_items_audited": 10,
    "compliant_count": 3,
    "deviation_count": 4,
    "silent_count": 3,
    "overall_risk_rating": "HIGH",
    "results": [
        {
            "item_id": "REQ-01",
            "item_name": "Service Level Agreement (SLA)",
            "status": "MET",
            "alignment_degree": "ALIGNED_STANDARD",
            "confidence": "HIGH",
            "policy_standard": ">= 99.9% monthly uptime",
            "identified_contract_term": "99.9% System Availability commitment",
            "exact_citation": 'Section 8.1 ("...operational System Availability of at least ninety-nine and nine-tenths percent (99.9%)...")',
            "deviation_analysis": None,
        },
        {
            "item_id": "REQ-02",
            "item_name": "SLA Service Credits",
            "status": "SILENT",
            "alignment_degree": "SILENT",
            "confidence": "HIGH",
            "policy_standard": ">= 10% monthly credit per 0.5% outage",
            "identified_contract_term": "Omitted / Silent",
            "exact_citation": "Not Found / Silent",
            "deviation_analysis": "No financial remedy provided for system downtime.",
        },
        {
            "item_id": "REQ-03",
            "item_name": "Auto-Renewal Notice Window",
            "status": "DEVIATION",
            "alignment_degree": "MATERIAL_DEVIATION",
            "confidence": "HIGH",
            "policy_standard": ">= 60 days prior notice",
            "identified_contract_term": "15 days notice required",
            "exact_citation": 'Section 5.1 ("...at least fifteen (15) days prior...")',
            "deviation_analysis": "Window is too short; creates risk of accidental auto-renewal.",
        },
        {
            "item_id": "REQ-04",
            "item_name": "Termination for Convenience",
            "status": "SILENT",
            "alignment_degree": "SILENT",
            "confidence": "HIGH",
            "policy_standard": "Permitted with <= 30 days written notice",
            "identified_contract_term": "Omitted / Silent",
            "exact_citation": "Not Found / Silent",
            "deviation_analysis": "Customer locked in for term unless vendor commits material breach.",
        },
        {
            "item_id": "REQ-05",
            "item_name": "Termination Assistance / Transition",
            "status": "DEVIATION",
            "alignment_degree": "PARTIAL_ALIGNMENT",
            "confidence": "HIGH",
            "policy_standard": "60 days support, no additional fee",
            "identified_contract_term": "14 days self-export only; no vendor support",
            "exact_citation": 'Section 5.3 ("...fourteen (14) days to self-export...")',
            "deviation_analysis": "Insufficient data migration window; risk of data loss.",
        },
        {
            "item_id": "REQ-06",
            "item_name": "Payment Terms",
            "status": "DEVIATION",
            "alignment_degree": "PARTIAL_ALIGNMENT",
            "confidence": "HIGH",
            "policy_standard": "Net 60 days",
            "identified_contract_term": "Net 30 days",
            "exact_citation": 'Section 3.2 ("...within thirty (30) calendar days...")',
            "deviation_analysis": "Working capital strain; departs from standard Net 60 policy.",
        },
        {
            "item_id": "REQ-07",
            "item_name": "Price Escalation Cap",
            "status": "DEVIATION",
            "alignment_degree": "MATERIAL_DEVIATION",
            "confidence": "HIGH",
            "policy_standard": "<= 3% or CPI annually",
            "identified_contract_term": "Up to 7.0% annual increase",
            "exact_citation": 'Section 3.3 ("...increase annual subscription fees by up to seven percent (7.0%)...")',
            "deviation_analysis": "Escalation exceeds 3% ceiling.",
        },
        {
            "item_id": "REQ-08",
            "item_name": "Mutual Indemnification",
            "status": "SILENT",
            "alignment_degree": "SILENT",
            "confidence": "HIGH",
            "policy_standard": "Uncapped IP infringement indemnity",
            "identified_contract_term": "Omitted / Silent",
            "exact_citation": "Not Found / Silent",
            "deviation_analysis": "Uncapped exposure if vendor infringes third-party IP.",
        },
        {
            "item_id": "REQ-09",
            "item_name": "Limitation of Liability Cap",
            "status": "MET",
            "alignment_degree": "ALIGNED_FALLBACK",
            "confidence": "MEDIUM",
            "policy_standard": "1x to 2x aggregate annual fees",
            "identified_contract_term": "Fees paid in preceding 12 months (1x)",
            "exact_citation": 'Section 11.2 ("...fees actually paid by Customer in the twelve (12) months...")',
            "deviation_analysis": None,
        },
        {
            "item_id": "REQ-10",
            "item_name": "Governing Law & Jurisdiction",
            "status": "MET",
            "alignment_degree": "ALIGNED_STANDARD",
            "confidence": "HIGH",
            "policy_standard": "State of Delaware or New York",
            "identified_contract_term": "State of Delaware",
            "exact_citation": 'Section 14.1 ("...laws of the State of Delaware.")',
            "deviation_analysis": None,
        },
    ],
}


def test_rubric_config_contract():
    """Verify that the declarative YAML contains all 10 required items, search terms, and engine settings."""
    auditor = ContractAuditor.__new__(ContractAuditor)
    # Mocking client initialization to inspect rubric loading purely
    auditor.model_name = "gemini-flash-latest"
    auditor.temperature = 0.0
    with open("config/audit_rubric.yaml", "r", encoding="utf-8") as f:
        import yaml

        config = yaml.safe_load(f)

    assert "rubric" in config
    assert "engine" in config
    assert "retrieval" in config["engine"]
    assert len(config["rubric"]) == 10

    # Assert critical columns and hybrid search definitions exist on every rubric item
    for item in config["rubric"]:
        assert "id" in item
        assert "name" in item
        assert "target_value" in item
        assert "criticality" in item
        assert "keywords" in item and len(item["keywords"]) > 0
        assert "magic_phrases" in item and len(item["magic_phrases"]) > 0


def test_mocked_contract_audit_pipeline(mocker, tmp_path):
    """Verify end-to-end hybrid retrieval, evaluation, schema parsing, and markdown/docx reporting using mocks."""
    # 1. Mock the Google GenAI Client so this runs fast and offline
    mock_genai_client = mocker.MagicMock()
    mock_response = mocker.MagicMock()
    mock_response.text = json.dumps(MOCK_AUDIT_PAYLOAD)
    mock_genai_client.models.generate_content.return_value = mock_response

    # 2. Instantiate the auditor and replace the live API client
    mocker.patch.dict(os.environ, {"GEMINI_API_KEY": "test-dummy-key"})
    auditor = ContractAuditor()
    auditor.client = mock_genai_client

    # 3. Execute the audit
    report = auditor.audit_contract(
        contract_text=SYNTHETIC_CONTRACT_TEXT,
        contract_title="Apex Cloud MSA",
        vendor_name="Apex Cloud Technologies, LLC",
    )

    # 4. Verify hybrid retrieval bundles were computed and passed into the LLM prompt
    assert len(auditor.last_retrieval_bundles) == 10
    bundle_map = {b.item_id: b for b in auditor.last_retrieval_bundles}
    assert bundle_map["REQ-01"].matches[0].clause.clause_id == "Section 8.1"
    assert bundle_map["REQ-10"].matches[0].clause.clause_id == "Section 14.1"

    called_prompt = mock_genai_client.models.generate_content.call_args.kwargs[
        "contents"
    ][0]
    assert "HYBRID SEARCH RETRIEVED EVIDENCE" in called_prompt
    assert "Matched Magic Phrases" in called_prompt

    # 5. Assert model counts, confidence counts, and validation integrity
    assert report.total_items_audited == 10
    assert report.compliant_count == 3
    assert report.deviation_count == 4
    assert report.silent_count == 3
    assert report.high_confidence_count == 9
    assert report.medium_confidence_count == 1
    assert report.low_confidence_count == 0
    assert report.overall_risk_rating == RiskCriticality.HIGH

    # 6. Assert specific compliance findings, alignment degrees, and confidence levels
    results_map = {r.item_id: r for r in report.results}

    # REQ-01: SLA (MET / ALIGNED_STANDARD / HIGH)
    assert results_map["REQ-01"].status == ComplianceStatus.MET
    assert results_map["REQ-01"].alignment_degree == AlignmentDegree.ALIGNED_STANDARD
    assert results_map["REQ-01"].confidence == ConfidenceLevel.HIGH
    assert "Section 8.1" in results_map["REQ-01"].exact_citation

    # REQ-02: SLA Credits (SILENT)
    assert results_map["REQ-02"].status == ComplianceStatus.SILENT
    assert results_map["REQ-02"].alignment_degree == AlignmentDegree.SILENT
    assert results_map["REQ-02"].exact_citation == "Not Found / Silent"

    # REQ-09: Liability Cap (MET / ALIGNED_FALLBACK / MEDIUM)
    assert results_map["REQ-09"].status == ComplianceStatus.MET
    assert results_map["REQ-09"].alignment_degree == AlignmentDegree.ALIGNED_FALLBACK
    assert results_map["REQ-09"].confidence == ConfidenceLevel.MEDIUM

    # 7. Test Markdown & Word (.docx) reporting generation
    report_file = tmp_path / "test_intake_sheet.md"
    docx_file = tmp_path / "test_intake_sheet.docx"
    rendered_path = render_compliance_markdown(report, report_file)
    rendered_docx = render_compliance_docx(report, docx_file)

    assert rendered_path.exists()
    assert rendered_docx.exists()
    markdown_content = rendered_path.read_text(encoding="utf-8")
    assert "Apex Cloud MSA" in markdown_content
    assert "✅ MET" in markdown_content
    assert "⚠️ DEVIATION" in markdown_content
    assert "❌ SILENT" in markdown_content
    assert "🟢 HIGH" in markdown_content
    assert "🟡 MEDIUM" in markdown_content
    assert "ALIGNED_FALLBACK" in markdown_content


def test_confidence_calibration_downgrades_ungrounded_citations_and_dangling_refs(
    mocker,
):
    """Verify post-validation calibration downgrades hallucinated citations to LOW and dangling refs to MEDIUM."""
    mocker.patch.dict(os.environ, {"GEMINI_API_KEY": "test-dummy-key"})
    auditor = ContractAuditor()

    full_contract_text = Path(
        "data/raw_contracts/generic_tech_vendor_contract.md"
    ).read_text(encoding="utf-8")
    clauses = DocumentParser().chunk_clauses(full_contract_text)
    bundles = auditor.retrieve_evidence(clauses)

    payload = json.loads(json.dumps(MOCK_AUDIT_PAYLOAD))
    # Inject a hallucinated citation on REQ-01 that does not exist in the contract
    payload["results"][0]["exact_citation"] = (
        'Section 99.9 ("Vendor guarantees 99.999% availability with triple credits.")'
    )
    payload["results"][0]["confidence"] = "HIGH"
    # Set REQ-09 confidence to HIGH even though Section 11.2 has a dangling reference to missing Section 9
    payload["results"][8]["confidence"] = "HIGH"

    raw_report = ContractAuditReport.model_validate(payload)
    calibrated = auditor.verify_and_calibrate_report(
        report=raw_report,
        contract_text=full_contract_text,
        bundles=bundles,
    )

    results_map = {r.item_id: r for r in calibrated.results}
    # REQ-01 must be downgraded to LOW because Section 99.9 does not exist in the contract
    assert results_map["REQ-01"].confidence == ConfidenceLevel.LOW
    # REQ-09 must be capped at MEDIUM because Section 11.2 references missing Section 9
    assert results_map["REQ-09"].confidence == ConfidenceLevel.MEDIUM
    assert calibrated.low_confidence_count == 1


def test_csv_scorecard_header_repair_and_slugify(tmp_path):
    """Verify slugify sanitizes unsafe filename chars and append_scorecard_csv repairs missing headers."""
    assert slugify_title("Apex Cloud / MSA: 2026*?") == "apex_cloud_msa_2026"

    report = ContractAuditReport.model_validate(MOCK_AUDIT_PAYLOAD)
    csv_file = tmp_path / "scorecard.csv"
    # Simulate a legacy headerless CSV file
    csv_file.write_text(
        'Old Contract,"Vendor, Inc.",10,3,4,3,CRITICAL\n', encoding="utf-8"
    )

    append_scorecard_csv(report, csv_file)
    lines = csv_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == (
        "contract_title,vendor_name,total_items,compliant_count,deviation_count,silent_count,overall_risk"
    )
    assert len(lines) == 3
    assert "Apex Cloud MSA" in lines[2]


@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not configured; skipping live API test.",
)
def test_live_gemini_contract_audit(tmp_path):
    """Executes a live end-to-end audit call against the Gemini API.

    Validates schema conformance, absence detection (SILENT),
    and markdown report persistence on disk.
    """
    contract_file = Path("data/raw_contracts/generic_tech_vendor_contract.md")
    assert contract_file.exists(), f"Contract file not found at {contract_file}"

    contract_text = contract_file.read_text(encoding="utf-8")

    auditor = ContractAuditor()
    report = auditor.audit_contract(
        contract_text=contract_text,
        contract_title="Apex Cloud MSA",
        vendor_name="Apex Cloud Technologies, LLC",
    )

    # 1. Structural integrity checks
    assert report.total_items_audited == 10
    assert report.compliant_count + report.deviation_count + report.silent_count == 10
    assert (
        report.high_confidence_count
        + report.medium_confidence_count
        + report.low_confidence_count
        == 10
    )
    assert len(report.results) == 10

    # 2. Absence verification (REQ-04: Termination for Convenience should be SILENT)
    results_map = {r.item_id: r for r in report.results}
    assert results_map["REQ-04"].status == ComplianceStatus.SILENT
    assert results_map["REQ-04"].alignment_degree == AlignmentDegree.SILENT

    # 3. Compliance verification (REQ-10: Governing Law should be MET)
    assert results_map["REQ-10"].status == ComplianceStatus.MET

    # 4. Generate the final markdown report artifact
    output_path = tmp_path / "live_audit_intake.md"
    rendered_file = render_compliance_markdown(report, output_path)
    assert rendered_file.exists()
    assert "Apex Cloud MSA" in rendered_file.read_text(encoding="utf-8")
