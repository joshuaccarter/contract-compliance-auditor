"""Unit tests for the contract document parser."""

from pathlib import Path
import pytest
from src.parsing.document_parser import DocumentParser, ParsedContract


def test_parser_markdown_normalization():
    """Verifies parsing and section extraction on markdown contracts."""
    contract_file = Path("data/raw_contracts/generic_tech_vendor_contract.md")
    assert contract_file.exists(), "Test contract fixture missing"

    parser = DocumentParser()
    result = parser.parse(contract_file)

    assert isinstance(result, ParsedContract)
    assert result.file_name == "generic_tech_vendor_contract.md"
    assert result.file_type == ".md"
    assert result.estimated_tokens > 100
    assert len(result.detected_sections) >= 4

    # Verify key sections were detected by heading heuristics
    joined_sections = " ".join(result.detected_sections).lower()
    assert "fees" in joined_sections or "invoicing" in joined_sections
    assert "term" in joined_sections or "renewals" in joined_sections


def test_parser_unsupported_format(tmp_path):
    """Verifies defensive error handling on unsupported file extensions."""
    invalid_file = tmp_path / "contract.xyz"
    invalid_file.write_text("Unsupported dummy data", encoding="utf-8")

    parser = DocumentParser()
    with pytest.raises(ValueError, match="Unsupported file format"):
        parser.parse(invalid_file)