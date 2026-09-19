"""CLI entry point to execute compliance audit and persist all deliverables."""

import argparse
import csv
from pathlib import Path

from src.audit.engine import ContractAuditor
from src.formatting.reporter import render_compliance_docx, render_compliance_markdown
from src.parsing.document_parser import DocumentParser


def append_scorecard_csv(report, csv_path: Path):
    """Appends high-level audit metrics to a central tracking ledger."""
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
    file_exists = csv_path.exists()

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
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


def main():
    parser = argparse.ArgumentParser(description="Contract Compliance Evaluation Runner")
    parser.add_argument(
        "--contract",
        default="data/raw_contracts/generic_tech_vendor_contract.md",
        help="Path to contract file",
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


    print(f"\n[1/4] Ingesting & normalizing contract: {contract_path.name}...")
    parser = DocumentParser()
    parsed_doc = parser.parse(contract_path)
    contract_text = parsed_doc.raw_text
    print(f"      Detected format: {parsed_doc.file_type} | Est. tokens: ~{parsed_doc.estimated_tokens}")
    print(f"      Found {len(parsed_doc.detected_sections)} structural sections.")

    print("[2/4] Executing compliance audit with Gemini Flash...")
    auditor = ContractAuditor()
    report = auditor.audit_contract(
        contract_text=contract_text,
        contract_title=args.title,
        vendor_name=args.vendor,
    )

    slug = args.title.lower().replace(" ", "_").replace(",", "")
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
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()