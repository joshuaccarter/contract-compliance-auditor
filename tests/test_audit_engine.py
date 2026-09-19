"""Automated unit and integration test suite for the contract compliance engine."""

import json
import os
from pathlib import Path

import pytest

from src.audit.engine import ContractAuditor
from src.audit.schemas import ComplianceStatus, RiskCriticality
from src.formatting.reporter import render_compliance_markdown

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
11.2 Liability Ceiling. Total aggregate liability limited strictly to fees actually paid in preceding twelve (12) months.

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
            "policy_standard": ">= 99.9% monthly uptime",
            "identified_contract_term": "99.9% System Availability commitment",
            "exact_citation": 'Section 8.1 ("...operational System Availability of at least 99.9%...")',
            "deviation_analysis": None,
        },
        {
            "item_id": "REQ-02",
            "item_name": "SLA Service Credits",
            "status": "SILENT",
            "policy_standard": ">= 10% monthly credit per 0.5% outage",
            "identified_contract_term": "Omitted / Silent",
            "exact_citation": "Not Found / Silent",
            "deviation_analysis": "No financial remedy provided for system downtime.",
        },
        {
            "item_id": "REQ-03",
            "item_name": "Auto-Renewal Notice Window",
            "status": "DEVIATION",
            "policy_standard": ">= 60 days prior notice",
            "identified_contract_term": "15 days notice required",
            "exact_citation": 'Section 5.1 ("...at least fifteen (15) days prior...")',
            "deviation_analysis": "Window is too short; creates risk of accidental auto-renewal.",
        },
        {
            "item_id": "REQ-04",
            "item_name": "Termination for Convenience",
            "status": "SILENT",
            "policy_standard": "Permitted with <= 30 days written notice",
            "identified_contract_term": "Omitted / Silent",
            "exact_citation": "Not Found / Silent",
            "deviation_analysis": "Customer locked in for term unless vendor commits material breach.",
        },
        {
            "item_id": "REQ-05",
            "item_name": "Termination Assistance / Transition",
            "status": "DEVIATION",
            "policy_standard": "60 days support, no additional fee",
            "identified_contract_term": "14 days self-export only; no vendor support",
            "exact_citation": 'Section 5.3 ("...fourteen (14) days to self-export...")',
            "deviation_analysis": "Insufficient data migration window; risk of data loss.",
        },
        {
            "item_id": "REQ-06",
            "item_name": "Payment Terms",
            "status": "DEVIATION",
            "policy_standard": "Net 60 days",
            "identified_contract_term": "Net 30 days",
            "exact_citation": 'Section 3.2 ("...within thirty (30) calendar days...")',
            "deviation_analysis": "Working capital strain; departs from standard Net 60 policy.",
        },
        {
            "item_id": "REQ-07",
            "item_name": "Price Escalation Cap",
            "status": "DEVIATION",
            "policy_standard": "<= 3% or CPI annually",
            "identified_contract_term": "Up to 7.0% annual increase",
            "exact_citation": 'Section 3.3 ("...increase annual subscription fees by up to seven percent (7.0%)...")',
            "deviation_analysis": "Escalation exceeds 3% ceiling.",
        },
        {
            "item_id": "REQ-08",
            "item_name": "Mutual Indemnification",
            "status": "SILENT",
            "policy_standard": "Uncapped IP infringement indemnity",
            "identified_contract_term": "Omitted / Silent",
            "exact_citation": "Not Found / Silent",
            "deviation_analysis": "Uncapped exposure if vendor infringes third-party IP.",
        },
        {
            "item_id": "REQ-09",
            "item_name": "Limitation of Liability Cap",
            "status": "MET",
            "policy_standard": "1x to 2x aggregate annual fees",
            "identified_contract_term": "Fees paid in preceding 12 months (1x)",
            "exact_citation": 'Section 11.2 ("...fees actually paid by Customer in the twelve (12) months...")',
            "deviation_analysis": None,
        },
        {
            "item_id": "REQ-10",
            "item_name": "Governing Law & Jurisdiction",
            "status": "MET",
            "policy_standard": "State of Delaware or New York",
            "identified_contract_term": "State of Delaware",
            "exact_citation": 'Section 14.1 ("...laws of the State of Delaware...")',
            "deviation_analysis": None,
        },
    ],
}


def test_rubric_config_contract():
    """Verify that the declarative YAML contains all 10 required items and engine settings."""
    auditor = ContractAuditor.__new__(ContractAuditor)
    # Mocking client initialization to inspect rubric loading purely
    auditor.model_name = "gemini-flash-latest"
    auditor.temperature = 0.0
    with open("config/audit_rubric.yaml", "r", encoding="utf-8") as f:
        import yaml
        config = yaml.safe_load(f)

    assert "rubric" in config
    assert "engine" in config
    assert len(config["rubric"]) == 10
    
    # Assert critical columns exist on every rubric item
    for item in config["rubric"]:
        assert "id" in item
        assert "name" in item
        assert "target_value" in item
        assert "criticality" in item


def test_mocked_contract_audit_pipeline(mocker, tmp_path):
    """Verify end-to-end evaluation, schema parsing, and markdown reporting using mocks."""
    # 1. Mock the Google GenAI Client so this runs fast and offline
    mock_genai_client = mocker.MagicMock()
    mock_response = mocker.MagicMock()
    mock_response.text = json.dumps(MOCK_AUDIT_PAYLOAD)
    mock_genai_client.models.generate_content.return_value = mock_response

    # 2. Instantiate the auditor and replace the live API client
    auditor = ContractAuditor()
    auditor.client = mock_genai_client

    # 3. Execute the audit
    report = auditor.audit_contract(
        contract_text=SYNTHETIC_CONTRACT_TEXT,
        contract_title="Apex Cloud MSA",
        vendor_name="Apex Cloud Technologies, LLC",
    )

    # 4. Assert model counts and validation integrity
    assert report.total_items_audited == 10
    assert report.compliant_count == 3
    assert report.deviation_count == 4
    assert report.silent_count == 3
    assert report.overall_risk_rating == RiskCriticality.HIGH

    # 5. Assert specific compliance findings
    results_map = {r.item_id: r for r in report.results}
    
    # REQ-01: SLA (MET)
    assert results_map["REQ-01"].status == ComplianceStatus.MET
    assert "Section 8.1" in results_map["REQ-01"].exact_citation

    # REQ-02: SLA Credits (SILENT)
    assert results_map["REQ-02"].status == ComplianceStatus.SILENT
    assert results_map["REQ-02"].exact_citation == "Not Found / Silent"

    # REQ-03: Renewal (DEVIATION - 15 days vs 60 days)
    assert results_map["REQ-03"].status == ComplianceStatus.DEVIATION
    assert "15" in results_map["REQ-03"].identified_contract_term

    # 6. Test output reporting generation
    report_file = tmp_path / "test_intake_sheet.md"
    rendered_path = render_compliance_markdown(report, report_file)

    assert rendered_path.exists()
    markdown_content = rendered_path.read_text(encoding="utf-8")
    assert "Apex Cloud MSA" in markdown_content
    assert "✅ MET" in markdown_content
    assert "⚠️ DEVIATION" in markdown_content
    assert "❌ SILENT" in markdown_content



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
    assert (
        report.compliant_count + report.deviation_count + report.silent_count == 10
    )
    assert len(report.results) == 10

    # 2. Absence verification (REQ-04: Termination for Convenience should be SILENT)
    results_map = {r.item_id: r for r in report.results}
    assert results_map["REQ-04"].status == ComplianceStatus.SILENT

    # 3. Compliance verification (REQ-10: Governing Law should be MET)
    assert results_map["REQ-10"].status == ComplianceStatus.MET

    # 4. Generate the final markdown report artifact
    output_path = tmp_path / "live_audit_intake.md"
    rendered_file = render_compliance_markdown(report, output_path)
    assert rendered_file.exists()
    assert "Apex Cloud MSA" in rendered_file.read_text(encoding="utf-8")