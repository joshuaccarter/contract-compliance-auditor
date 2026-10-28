"""CLI entry point to execute compliance audit and persist all deliverables."""

import argparse
import csv
import re
from pathlib import Path

from src.audit.engine import ContractAuditor
from src.audit.schemas import ContractAuditReport
from src.formatting.reporter import render_compliance_docx, render_compliance_markdown
from src.parsing.document_parser import DocumentParser


def slugify_title(title: str) -> str:
    """Normalizes a contract title into a safe, cross-platform filename slug."""
    slug = re.sub(r"[^a-z0-9_-]+", "_", title.lower()).strip("_")
    return slug or "contract"


def append_scorecard_csv(report: ContractAuditReport, csv_path: Path) -> None:
    """Appends high-level audit metrics to a central tracking ledger, ensuring headers exist."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "contract_title",
        "vendor_name",
        "total_items",
        "compliant_count",
        "deviation_count",
        "silent_count",
        "overall_risk",
    ]

    needs_header = True
    if csv_path.exists() and csv_path.stat().st_size > 0:
        existing_text = csv_path.read_text(encoding="utf-8")
        first_line = existing_text.splitlines()[0].strip() if existing_text else ""
        if first_line.startswith("contract_title,"):
            needs_header = False
        else:
            # Repair legacy headerless CSV before appending new row
            header_line = ",".join(fieldnames) + "\n"
            csv_path.write_text(header_line + existing_text, encoding="utf-8")
            needs_header = False

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if needs_header:
            writer.writeheader()
        writer.writerow(
            {
                "contract_title": report.contract_title,
                "vendor_name": report.vendor_name,
                "total_items": report.total_items_audited,
                "compliant_count": report.compliant_count,
                "deviation_count": report.deviation_count,
                "silent_count": report.silent_count,
                "overall_risk": report.overall_risk_rating.value,
            }
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Contract Compliance Evaluation Runner"
    )
    parser.add_argument(
        "--contract",
        default="data/raw_contracts/generic_tech_vendor_contract.md",
        help="Path to primary contract file being onboarded (Level 0, highest precedence)",
    )
    parser.add_argument(
        "--parent-contracts",
        nargs="*",
        default=[],
        help=(
            "Optional governing parent contract paths ordered from immediate parent (L1, e.g. SOW) "
            "up to the root master agreement (Ln, e.g. MSA)"
        ),
    )
    parser.add_argument(
        "--title",
        default="Apex Cloud Master Services Agreement",
        help="Display title of the contract",
    )
    parser.add_argument(
        "--vendor",
        default="Apex Cloud Technologies, LLC",
        help="Name of vendor entity",
    )
    args = parser.parse_args()

    contract_path = Path(args.contract)
    if not contract_path.exists():
        raise FileNotFoundError(f"Contract not found: {contract_path}")

    parent_paths = [Path(p) for p in args.parent_contracts]
    for p_path in parent_paths:
        if not p_path.exists():
            raise FileNotFoundError(f"Parent contract not found: {p_path}")

    doc_parser = DocumentParser()
    if parent_paths:
        all_paths = [contract_path, *parent_paths]
        chain_str = " -> ".join(
            f"L{idx}:{p.name}" for idx, p in enumerate(all_paths)
        )
        print(f"\n[1/4] Ingesting recursive contract hierarchy: {chain_str}...")
        parsed_doc = doc_parser.parse_hierarchy(all_paths)
        resolved_clauses = parsed_doc.resolve_hierarchical_clauses()
        contract_text = parsed_doc.compile_hierarchical_text()
        total_tokens = sum(
            node.estimated_tokens for node in parsed_doc.iter_hierarchy()
        )
        print(
            f"      Hierarchy depth: {len(all_paths)} documents | Combined est. tokens: ~{total_tokens}"
        )
        print(
            f"      Resolved {len(resolved_clauses)} total hierarchical clause chunks."
        )
    else:
        print(
            f"\n[1/4] Ingesting, normalizing & chunking contract: {contract_path.name}..."
        )
        parsed_doc = doc_parser.parse(contract_path)
        contract_text = parsed_doc.raw_text
        print(
            f"      Detected format: {parsed_doc.file_type} | Est. tokens: ~{parsed_doc.estimated_tokens}"
        )
        print(
            f"      Found {len(parsed_doc.detected_sections)} structural sections and {len(parsed_doc.clauses)} clause chunks."
        )

    print(
        "[2/4] Executing hybrid search (dense + sparse) & compliance audit with Gemini..."
    )
    auditor = ContractAuditor()
    report = auditor.audit_contract(
        contract_text=contract_text,
        contract_title=args.title,
        vendor_name=args.vendor,
        parsed_contract=parsed_doc,
    )

    slug = slugify_title(args.title)
    md_out = Path(f"reports/audit_results/{slug}_assessment.md")
    docx_out = Path(f"reports/audit_results/{slug}_assessment.docx")
    csv_ledger = Path("reports/compliance_scorecard.csv")

    print(f"[3/4] Rendering Markdown report: {md_out}...")
    render_compliance_markdown(report, md_out)

    print(f"[4/4] Rendering Word (.docx) intake sheet: {docx_out}...")
    render_compliance_docx(report, docx_out)

    append_scorecard_csv(report, csv_ledger)
    print(f"Summary metrics logged to: {csv_ledger}")

    print("\n" + "=" * 65)
    print("           AUDIT INTAKE COMPLETE           ")
    print("=" * 65)
    print(f"Risk Rating:    {report.overall_risk_rating.value}")
    print(f"Passed (MET):   {report.compliant_count} / {report.total_items_audited}")
    print(f"Deviations:     {report.deviation_count} / {report.total_items_audited}")
    print(f"Silent/Missing: {report.silent_count} / {report.total_items_audited}")
    print(
        f"Confidence:     {report.high_confidence_count} HIGH | {report.medium_confidence_count} MEDIUM | {report.low_confidence_count} LOW"
    )
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
