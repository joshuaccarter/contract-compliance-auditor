"""Data validation and serialization schemas for contract compliance evaluation."""

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ComplianceStatus(str, Enum):
    """Determination of contract clause against policy standard."""

    MET = "MET"
    DEVIATION = "DEVIATION"
    SILENT = "SILENT"


class AlignmentDegree(str, Enum):
    """Granular degree to which the identified contract clause aligns with the standard."""

    ALIGNED_STANDARD = "ALIGNED_STANDARD"
    ALIGNED_FALLBACK = "ALIGNED_FALLBACK"
    PARTIAL_ALIGNMENT = "PARTIAL_ALIGNMENT"
    MATERIAL_DEVIATION = "MATERIAL_DEVIATION"
    SILENT = "SILENT"


class ConfidenceLevel(str, Enum):
    """Confidence level of the review agent in the clause match and compliance verdict."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RiskCriticality(str, Enum):
    """Impact severity of a policy deviation or missing clause."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ItemAuditResult(BaseModel):
    """Evaluation result for an individual compliance checklist item."""

    item_id: str = Field(
        ...,
        description="Unique identifier from the policy rubric, e.g. 'REQ-01'",
    )
    item_name: str = Field(
        ...,
        description="Descriptive title of the audited requirement",
    )
    status: ComplianceStatus = Field(
        ...,
        description="Audit verdict: MET, DEVIATION, or SILENT",
    )
    alignment_degree: AlignmentDegree = Field(
        default=AlignmentDegree.ALIGNED_STANDARD,
        description=(
            "Granular alignment degree: ALIGNED_STANDARD (meets primary target), "
            "ALIGNED_FALLBACK (meets acceptable fallback), PARTIAL_ALIGNMENT (minor gap), "
            "MATERIAL_DEVIATION (major policy departure), or SILENT (omitted)"
        ),
    )
    confidence: ConfidenceLevel = Field(
        default=ConfidenceLevel.HIGH,
        description="Confidence level in clause identification and alignment assessment: HIGH, MEDIUM, or LOW",
    )
    policy_standard: str = Field(
        ...,
        description="Standard baseline required by enterprise policy",
    )
    identified_contract_term: str = Field(
        ...,
        description="Verbatim extraction or summary of the vendor's actual terms",
    )
    exact_citation: str = Field(
        ...,
        description="Section reference and direct quote from contract, or 'Not Found / Silent'",
    )
    deviation_analysis: str | None = Field(
        default=None,
        description="Analysis of legal/financial exposure if status is DEVIATION or SILENT",
    )

    @model_validator(mode="after")
    def sync_alignment_with_status(self) -> "ItemAuditResult":
        """Ensure alignment_degree and status remain mutually consistent."""
        if self.status == ComplianceStatus.SILENT:
            self.alignment_degree = AlignmentDegree.SILENT
            if not self.exact_citation or self.exact_citation.strip() == "":
                self.exact_citation = "Not Found / Silent"
        elif self.status == ComplianceStatus.MET:
            if self.alignment_degree not in (
                AlignmentDegree.ALIGNED_STANDARD,
                AlignmentDegree.ALIGNED_FALLBACK,
            ):
                self.alignment_degree = AlignmentDegree.ALIGNED_STANDARD
        elif self.status == ComplianceStatus.DEVIATION and self.alignment_degree not in (
            AlignmentDegree.PARTIAL_ALIGNMENT,
            AlignmentDegree.MATERIAL_DEVIATION,
        ):
            self.alignment_degree = AlignmentDegree.MATERIAL_DEVIATION
        return self


class ContractAuditReport(BaseModel):
    """Aggregated contract compliance audit report."""

    contract_title: str = Field(
        ...,
        description="Title or reference header of the audited contract",
    )
    vendor_name: str = Field(
        ...,
        description="Name of the contracting vendor entity",
    )
    total_items_audited: int = Field(
        default=10,
        ge=1,
        description="Total checklist items evaluated",
    )
    compliant_count: int = Field(
        default=0,
        description="Number of items marked MET",
    )
    deviation_count: int = Field(
        default=0,
        description="Number of items marked DEVIATION",
    )
    silent_count: int = Field(
        default=0,
        description="Number of items marked SILENT",
    )
    high_confidence_count: int = Field(
        default=0,
        description="Number of items evaluated with HIGH confidence",
    )
    medium_confidence_count: int = Field(
        default=0,
        description="Number of items evaluated with MEDIUM confidence",
    )
    low_confidence_count: int = Field(
        default=0,
        description="Number of items evaluated with LOW confidence",
    )
    overall_risk_rating: RiskCriticality = Field(
        ...,
        description="Composite contract risk assessment",
    )
    results: list[ItemAuditResult] = Field(
        ...,
        description="Collection of individual item audit evaluations",
    )

    def recalculate_counts(self) -> "ContractAuditReport":
        """Recalculate summary and confidence counts directly from the results array to eliminate LLM arithmetic drift."""
        self.compliant_count = sum(
            1 for r in self.results if r.status == ComplianceStatus.MET
        )
        self.deviation_count = sum(
            1 for r in self.results if r.status == ComplianceStatus.DEVIATION
        )
        self.silent_count = sum(
            1 for r in self.results if r.status == ComplianceStatus.SILENT
        )
        self.high_confidence_count = sum(
            1 for r in self.results if r.confidence == ConfidenceLevel.HIGH
        )
        self.medium_confidence_count = sum(
            1 for r in self.results if r.confidence == ConfidenceLevel.MEDIUM
        )
        self.low_confidence_count = sum(
            1 for r in self.results if r.confidence == ConfidenceLevel.LOW
        )
        self.total_items_audited = len(self.results)
        return self

    @model_validator(mode="after")
    def sync_and_validate_counts(self) -> "ContractAuditReport":
        """Pydantic post-init validator hook to synchronize all summary counts."""
        return self.recalculate_counts()
