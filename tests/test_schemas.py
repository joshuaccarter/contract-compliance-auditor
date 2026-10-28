"""Unit tests for Pydantic schema validation, calculated counts, alignment degrees, confidence levels, and Gemini compatibility."""

import pytest
from pydantic import ValidationError

from src.audit.schemas import (
    AlignmentDegree,
    ComplianceStatus,
    ConfidenceLevel,
    ContractAuditReport,
    ItemAuditResult,
    RiskCriticality,
)


def _make_dummy_item(
    item_id: str,
    status: ComplianceStatus,
    name: str = "Test Item",
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
    alignment_degree: AlignmentDegree = AlignmentDegree.ALIGNED_STANDARD,
) -> ItemAuditResult:
    """Helper to construct minimal valid ItemAuditResult instances."""
    return ItemAuditResult(
        item_id=item_id,
        item_name=name,
        status=status,
        alignment_degree=alignment_degree,
        confidence=confidence,
        policy_standard="Standard specification",
        identified_contract_term="Contract term text",
        exact_citation="Section 1.1 ('test quote')",
        deviation_analysis=None
        if status == ComplianceStatus.MET
        else "Risk exposure note",
    )


def test_schema_forbids_examples_in_json_schema():
    """Ensure no schema fields export an 'examples' key that triggers Gemini schema validation errors."""
    report_schema = ContractAuditReport.model_json_schema()
    item_schema = ItemAuditResult.model_json_schema()

    # Verify top-level properties do not contain 'examples'
    for prop_name, prop_data in report_schema.get("properties", {}).items():
        assert "examples" not in prop_data, (
            f"ContractAuditReport property '{prop_name}' contains forbidden 'examples' key"
        )

    # Verify ItemAuditResult properties do not contain 'examples'
    for prop_name, prop_data in item_schema.get("properties", {}).items():
        assert "examples" not in prop_data, (
            f"ItemAuditResult property '{prop_name}' contains forbidden 'examples' key"
        )


def test_audit_report_auto_computes_counts_and_confidence():
    """Verify that model_validator automatically derives status and confidence counts from results list."""
    results = [
        _make_dummy_item(
            "REQ-01",
            ComplianceStatus.MET,
            confidence=ConfidenceLevel.HIGH,
            alignment_degree=AlignmentDegree.ALIGNED_STANDARD,
        ),
        _make_dummy_item(
            "REQ-02", ComplianceStatus.SILENT, confidence=ConfidenceLevel.HIGH
        ),
        _make_dummy_item(
            "REQ-03",
            ComplianceStatus.DEVIATION,
            confidence=ConfidenceLevel.HIGH,
            alignment_degree=AlignmentDegree.MATERIAL_DEVIATION,
        ),
        _make_dummy_item(
            "REQ-04", ComplianceStatus.SILENT, confidence=ConfidenceLevel.HIGH
        ),
        _make_dummy_item(
            "REQ-05",
            ComplianceStatus.DEVIATION,
            confidence=ConfidenceLevel.MEDIUM,
            alignment_degree=AlignmentDegree.PARTIAL_ALIGNMENT,
        ),
        _make_dummy_item(
            "REQ-06", ComplianceStatus.DEVIATION, confidence=ConfidenceLevel.HIGH
        ),
        _make_dummy_item(
            "REQ-07", ComplianceStatus.DEVIATION, confidence=ConfidenceLevel.HIGH
        ),
        _make_dummy_item(
            "REQ-08", ComplianceStatus.SILENT, confidence=ConfidenceLevel.LOW
        ),
        _make_dummy_item(
            "REQ-09",
            ComplianceStatus.MET,
            name="Limitation of Liability Cap",
            confidence=ConfidenceLevel.MEDIUM,
            alignment_degree=AlignmentDegree.ALIGNED_FALLBACK,
        ),
        _make_dummy_item(
            "REQ-10",
            ComplianceStatus.MET,
            name="Governing Law",
            confidence=ConfidenceLevel.HIGH,
        ),
    ]

    # Deliberately supply mismatched initial counts (e.g. 0, 0, 0)
    report = ContractAuditReport(
        contract_title="Apex Cloud MSA",
        vendor_name="Apex Cloud Technologies, LLC",
        total_items_audited=10,
        compliant_count=0,
        deviation_count=0,
        silent_count=0,
        high_confidence_count=0,
        medium_confidence_count=0,
        low_confidence_count=0,
        overall_risk_rating=RiskCriticality.HIGH,
        results=results,
    )

    # Assert validator recalculated the counts from results
    assert report.compliant_count == 3
    assert report.deviation_count == 4
    assert report.silent_count == 3
    assert report.high_confidence_count == 7
    assert report.medium_confidence_count == 2
    assert report.low_confidence_count == 1
    assert report.total_items_audited == 10


def test_alignment_degree_synchronizes_with_status():
    """Verify that ItemAuditResult keeps alignment_degree consistent with status."""
    silent_item = _make_dummy_item(
        "REQ-02",
        ComplianceStatus.SILENT,
        alignment_degree=AlignmentDegree.ALIGNED_STANDARD,
    )
    assert silent_item.alignment_degree == AlignmentDegree.SILENT

    dev_item = _make_dummy_item("REQ-03", ComplianceStatus.DEVIATION)
    assert dev_item.alignment_degree == AlignmentDegree.MATERIAL_DEVIATION

    fallback_item = _make_dummy_item(
        "REQ-09",
        ComplianceStatus.MET,
        alignment_degree=AlignmentDegree.ALIGNED_FALLBACK,
    )
    assert fallback_item.alignment_degree == AlignmentDegree.ALIGNED_FALLBACK


def test_option_a_req09_liability_cap_met_contract():
    """Verify REQ-09 evaluates cleanly as MET under Option A fallback rules."""
    req_09 = ItemAuditResult(
        item_id="REQ-09",
        item_name="Limitation of Liability Cap",
        status=ComplianceStatus.MET,
        alignment_degree=AlignmentDegree.ALIGNED_FALLBACK,
        confidence=ConfidenceLevel.MEDIUM,
        policy_standard="1x to 2x aggregate annual fees",
        identified_contract_term="Vendor's liability ceiling limited to fees actually paid in preceding 12 months.",
        exact_citation="Section 11.2 ('...fees actually paid by Customer in the twelve (12) months preceding the claim.')",
        deviation_analysis=None,
    )

    assert req_09.status == ComplianceStatus.MET
    assert req_09.alignment_degree == AlignmentDegree.ALIGNED_FALLBACK
    assert req_09.confidence == ConfidenceLevel.MEDIUM
    assert req_09.deviation_analysis is None
    assert "11.2" in req_09.exact_citation


def test_invalid_compliance_status_rejected():
    """Verify that unconstrained categorical strings fail schema validation."""
    with pytest.raises(ValidationError):
        _make_dummy_item("REQ-01", "PARTIALLY_COMPLIANT")  # type: ignore
    with pytest.raises(ValidationError):
        _make_dummy_item("REQ-01", ComplianceStatus.MET, confidence="CERTAIN")  # type: ignore
