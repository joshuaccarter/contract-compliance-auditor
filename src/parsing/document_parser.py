"""Layout-aware contract document parser supporting Markdown, DOCX, and PDF formats."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import List, Optional, Union
from docx import Document


@dataclass
class ParsedContract:
    """Standardized representation of an ingested and normalized contract."""

    raw_text: str
    file_name: str
    file_type: str
    detected_sections: List[str]
    estimated_tokens: int


class DocumentParser:
    """Normalizes contracts from various document formats into clean text for LLM ingestion."""

    SUPPORTED_EXTENSIONS = {".md", ".txt", ".docx"}

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Heuristic token estimation (~0.75 words per token)."""
        words = len(text.split())
        return int(words * 1.33)

    @staticmethod
    def _extract_sections(text: str) -> List[str]:
        """Identifies major section headings across standard contractual conventions."""
        # Matches patterns like '## Section 1', 'Section 1:', 'ARTICLE 3', or '3.1 Invoicing'
        section_pattern = re.compile(
            r"(?:^|\n)(?:#{1,3}\s*|Section\s+\d+|ARTICLE\s+[IVXLCDM\d]+|\d+\.\d+)\s*[:\.\s-]*([^\n]+)",
            re.IGNORECASE,
        )
        matches = section_pattern.findall(text)
        return [m.strip() for m in matches if len(m.strip()) > 3][:30]

    def _parse_docx(self, path: Path) -> str:
        """Extracts text and tabular content from Microsoft Word documents."""
        doc = Document(path)
        blocks: List[str] = []

        for p in doc.paragraphs:
            text = p.text.strip()
            if text:
                # Retain markdown-style headings if the paragraph style indicates a heading
                if p.style.name.startswith("Heading"):
                    blocks.append(f"## {text}")
                else:
                    blocks.append(text)

        for table in doc.tables:
            table_lines: List[str] = []
            for row in table.rows:
                row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                table_lines.append("| " + " | ".join(row_cells) + " |")
            if table_lines:
                blocks.append("\n" + "\n".join(table_lines) + "\n")

        return "\n\n".join(blocks)

    def parse(self, file_path: Union[str, Path]) -> ParsedContract:
        """Parses a contract file into a normalized ParsedContract object.

        Args:
            file_path: Path to the target contract (.md, .txt, .docx).

        Returns:
            ParsedContract containing normalized text and extracted structural metadata.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Contract file not found at: {path}")

        ext = path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file format '{ext}'. Supported extensions: {self.SUPPORTED_EXTENSIONS}"
            )

        if ext in (".md", ".txt"):
            raw_text = path.read_text(encoding="utf-8")
        elif ext == ".docx":
            raw_text = self._parse_docx(path)
        else:
            raise NotImplementedError(f"Format parser for {ext} not yet implemented.")

        # Clean carriage returns and trailing whitespace
        normalized_text = raw_text.replace("\r\n", "\n").strip()
        detected_sections = self._extract_sections(normalized_text)
        token_estimate = self._estimate_tokens(normalized_text)

        return ParsedContract(
            raw_text=normalized_text,
            file_name=path.name,
            file_type=ext,
            detected_sections=detected_sections,
            estimated_tokens=token_estimate,
        )