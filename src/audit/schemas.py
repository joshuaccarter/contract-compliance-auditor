"""Data validation and serialization schemas for contract compliance evaluation."""

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ComplianceStatus(str, Enum):
    """Determination of contract clause against policy standard."""

    MET = "MET"
    DEVIATION = "DEVIATION"
    SILENT = "SILENT"


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
    overall_risk_rating: RiskCriticality = Field(
        ...,
        description="Composite contract risk assessment",
    )
    results: list[ItemAuditResult] = Field(
        ...,
        description="Collection of individual item audit evaluations",
    )

    @model_validator(mode="after")
    def sync_and_validate_counts(self) -> "ContractAuditReport":
        """Recalculate summary counts directly from the results array to eliminate LLM arithmetic drift."""
        self.compliant_count = sum(
            1 for r in self.results if r.status == ComplianceStatus.MET
        )
        self.deviation_count = sum(
            1 for r in self.results if r.status == ComplianceStatus.DEVIATION
        )
        self.silent_count = sum(
            1 for r in self.results if r.status == ComplianceStatus.SILENT
        )
        self.total_items_audited = len(self.results)
        return self
