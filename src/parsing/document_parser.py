"""Layout-aware contract document parser and clause-level structural chunker."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


@dataclass
class ContractClause:
    """Represents a discrete, structurally bounded clause or section chunk from a contract."""

    clause_id: str
    section_heading: str
    clause_title: str
    text: str
    token_estimate: int
    referenced_sections: list[str] = field(default_factory=list)


@dataclass
class ParsedContract:
    """Standardized representation of an ingested, normalized, and chunked contract."""

    raw_text: str
    file_name: str
    file_type: str
    detected_sections: list[str]
    estimated_tokens: int
    clauses: list[ContractClause] = field(default_factory=list)


class DocumentParser:
    """Normalizes contracts from various document formats and chunks them into legal clauses."""

    SUPPORTED_EXTENSIONS: ClassVar[set[str]] = {".md", ".txt", ".docx"}

    # Matches top-level Markdown headings or standalone Section/Article headers
    _SECTION_HEADING_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:#{1,3}\s+(.+)|((?:Section|ARTICLE)\s+[IVXLCDM\d]+(?:\s*[:\.\-—]\s*[^\n]+)?))$",
        re.IGNORECASE,
    )

    # Matches numbered clauses such as '3.1 Subscription Fees. Customer shall...'
    _NUMBERED_CLAUSE_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"^(\d+\.\d+(?:\.\d+)?)\s+(?:([A-Z][A-Za-z0-9\s,&/\-\(\)]{1,65}?)\.\s+)?(.+)$"
    )

    # Matches explicit cross-references inside clause bodies, e.g., 'Section 9' or 'Section 11.2'
    _CROSS_REF_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"\b(?:Section|Article|Clause)s?\s+(\d+(?:\.\d+)?)\b",
        re.IGNORECASE,
    )

    def __init__(self, max_clause_chars: int = 1500, overlap_chars: int = 200):
        """Initialize parser with structural chunking boundaries."""
        self.max_clause_chars = max_clause_chars
        self.overlap_chars = overlap_chars

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Heuristic token estimation (~0.75 words per token)."""
        words = len(text.split())
        return max(1, int(words * 1.33)) if words else 0

    @classmethod
    def _extract_cross_references(cls, text: str, own_clause_id: str) -> list[str]:
        """Extracts cross-referenced section or clause numbers mentioned in text."""
        own_num = re.sub(
            r"^(?:Section|Article|Clause)\s+", "", own_clause_id, flags=re.IGNORECASE
        ).strip()
        refs: list[str] = []
        for match in cls._CROSS_REF_RE.findall(text):
            ref_num = match.strip()
            if (
                ref_num != own_num
                and not own_num.startswith(f"{ref_num}.")
                and ref_num not in refs
            ):
                refs.append(ref_num)
        return refs

    @staticmethod
    def _extract_sections(text: str) -> list[str]:
        """Identifies major section headings and numbered clause titles across contractual conventions."""
        section_pattern = re.compile(
            r"(?:^|\n)(?:#{1,3}\s*|(?:Section\s+\d+|ARTICLE\s+[IVXLCDM\d]+|\d+\.\d+)\s*[:\.\s-]*)"
            r"([^\n]+)",
            re.IGNORECASE,
        )
        matches = section_pattern.findall(text)
        return [m.strip() for m in matches if len(m.strip()) > 3][:50]

    def _split_oversized_text(self, text: str) -> list[str]:
        """Splits an oversized clause body along paragraph or sentence boundaries with overlap."""
        if len(text) <= self.max_clause_chars:
            return [text]

        sentences = re.split(r"(?<=[.!?])\s+|\n\n+", text)
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_len = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if (
                current_len + len(sentence) + 1 > self.max_clause_chars
                and current_chunk
            ):
                joined = " ".join(current_chunk)
                chunks.append(joined)
                # Retain tail sentences for overlap context
                overlap_buffer: list[str] = []
                overlap_len = 0
                for prev_s in reversed(current_chunk):
                    if overlap_len + len(prev_s) <= self.overlap_chars:
                        overlap_buffer.insert(0, prev_s)
                        overlap_len += len(prev_s) + 1
                    else:
                        break
                current_chunk = overlap_buffer
                current_len = sum(len(s) for s in current_chunk) + len(current_chunk)

            current_chunk.append(sentence)
            current_len += len(sentence) + 1

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks

    def chunk_clauses(self, normalized_text: str) -> list[ContractClause]:
        """Segments normalized contract text into hierarchical, clause-bounded chunks."""
        if not normalized_text.strip():
            return []

        lines = normalized_text.split("\n")
        raw_clauses: list[tuple[str, str, str, list[str]]] = []

        current_section_heading = "Preamble & Parties"
        current_clause_id = "PREAMBLE"
        current_clause_title = "Preamble & Agreement Metadata"
        current_buffer: list[str] = []

        def flush_buffer() -> None:
            nonlocal current_buffer
            body = "\n".join(current_buffer).strip()
            if body:
                raw_clauses.append(
                    (
                        current_clause_id,
                        current_section_heading,
                        current_clause_title,
                        [body],
                    )
                )
            current_buffer = []

        section_counter = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_buffer:
                    current_buffer.append("")
                continue

            # 1. Check for major section / article heading
            heading_match = self._SECTION_HEADING_RE.match(stripped)
            if heading_match:
                heading_text = (
                    heading_match.group(1) or heading_match.group(2) or ""
                ).strip()
                # Treat top-level document title on first line as part of preamble
                if (
                    current_clause_id == "PREAMBLE"
                    and not current_buffer
                    and stripped.startswith("# ")
                ):
                    current_buffer.append(stripped)
                    continue

                flush_buffer()
                section_counter += 1
                current_section_heading = heading_text
                sec_num_match = re.search(
                    r"\b(?:Section|ARTICLE)\s+([IVXLCDM\d]+)",
                    heading_text,
                    re.IGNORECASE,
                )
                sec_id = (
                    f"Section {sec_num_match.group(1)}"
                    if sec_num_match
                    else f"SEC-{section_counter}"
                )
                current_clause_id = sec_id
                current_clause_title = heading_text
                continue

            # 2. Check for numbered sub-clause (e.g., '3.1 Subscription Fees. ...')
            clause_match = self._NUMBERED_CLAUSE_RE.match(stripped)
            if clause_match:
                flush_buffer()
                clause_num = clause_match.group(1).strip()
                clause_title = (clause_match.group(2) or "").strip()
                current_clause_id = f"Section {clause_num}"
                current_clause_title = clause_title or f"Clause {clause_num}"
                current_buffer.append(stripped)
                continue

            # 3. Continuation line (paragraph text, bullet item, or table row)
            current_buffer.append(stripped)

        flush_buffer()

        # Finalize ContractClause list with size splitting and cross-reference extraction
        clauses: list[ContractClause] = []
        for clause_id, sec_heading, clause_title, body_parts in raw_clauses:
            full_body = "\n".join(body_parts).strip()
            sub_chunks = self._split_oversized_text(full_body)
            for idx, chunk_text in enumerate(sub_chunks):
                part_id = (
                    clause_id
                    if len(sub_chunks) == 1
                    else f"{clause_id} (Part {idx + 1})"
                )
                clauses.append(
                    ContractClause(
                        clause_id=part_id,
                        section_heading=sec_heading,
                        clause_title=clause_title,
                        text=chunk_text,
                        token_estimate=self._estimate_tokens(chunk_text),
                        referenced_sections=self._extract_cross_references(
                            chunk_text, clause_id
                        ),
                    )
                )

        return clauses

    def _parse_docx(self, path: Path) -> str:
        """Extracts text and tabular content from Microsoft Word documents in reading order."""
        doc = Document(str(path))
        blocks: list[str] = []

        for item in doc.iter_inner_content():
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if text:
                    style_name = (
                        item.style.name if item.style and item.style.name else ""
                    )
                    if style_name.startswith("Heading"):
                        blocks.append(f"## {text}")
                    else:
                        blocks.append(text)
            elif isinstance(item, Table):
                table_lines: list[str] = []
                for row in item.rows:
                    row_cells = [
                        cell.text.strip().replace("\n", " ") for cell in row.cells
                    ]
                    table_lines.append("| " + " | ".join(row_cells) + " |")
                if table_lines:
                    blocks.append("\n" + "\n".join(table_lines) + "\n")

        return "\n\n".join(blocks)

    def parse_text(
        self,
        raw_text: str,
        file_name: str = "inline_contract.md",
        file_type: str = ".md",
    ) -> ParsedContract:
        """Normalizes and chunks raw contract text directly into a ParsedContract object."""
        normalized_text = raw_text.replace("\r\n", "\n").strip()
        detected_sections = self._extract_sections(normalized_text)
        token_estimate = self._estimate_tokens(normalized_text)
        clauses = self.chunk_clauses(normalized_text)

        return ParsedContract(
            raw_text=normalized_text,
            file_name=file_name,
            file_type=file_type,
            detected_sections=detected_sections,
            estimated_tokens=token_estimate,
            clauses=clauses,
        )

    def parse(self, file_path: str | Path) -> ParsedContract:
        """Parses a contract file into a normalized and clause-chunked ParsedContract object.

        Args:
            file_path: Path to the target contract (.md, .txt, .docx).

        Returns:
            ParsedContract containing normalized text, structural metadata, and clause chunks.
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

        return self.parse_text(
            raw_text=raw_text,
            file_name=path.name,
            file_type=ext,
        )
