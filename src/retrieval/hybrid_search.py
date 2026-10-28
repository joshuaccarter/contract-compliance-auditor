"""Hybrid dense (semantic) and sparse (BM25 + legal 'magic phrase') clause retrieval engine."""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import errors as genai_errors

from src.parsing.document_parser import ContractClause

logger = logging.getLogger(__name__)

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
    }
)

_OVERRIDE_MAGIC_PHRASES: tuple[str, ...] = (
    "notwithstanding",
    "supersedes",
    "hereby amended",
    "hereby replaced",
    "in the event of a conflict",
    "modified as follows",
)


@dataclass
class ClauseMatch:
    """Scored contract clause candidate produced by hybrid dense + sparse search."""

    clause: ContractClause
    rrf_score: float
    dense_score: float
    sparse_score: float
    dense_rank: int | None
    sparse_rank: int | None
    matched_magic_phrases: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    is_cross_reference: bool = False


@dataclass
class RubricRetrievalBundle:
    """Aggregated hybrid search results for a single compliance rubric component."""

    item_id: str
    item_name: str
    query_text: str
    matches: list[ClauseMatch] = field(default_factory=list)
    missing_cross_references: list[str] = field(default_factory=list)


class HybridContractRetriever:
    """Combines dense semantic embeddings and sparse lexical/magic-phrase search via RRF."""

    _TOKEN_RE = re.compile(r"\d+(?:\.\d+)?%?|[a-z0-9]+(?:-[a-z0-9]+)*")

    def __init__(
        self,
        client: genai.Client | None = None,
        embedding_model: str = "gemini-embedding-001",
        top_k: int = 3,
        dense_weight: float = 0.5,
        sparse_weight: float = 0.5,
        rrf_k: int = 60,
        magic_phrase_boost: float = 2.5,
        bm25_k1: float = 1.5,
        bm25_b: float = 0.75,
        min_dense_score: float = 0.08,
    ):
        """Initialize the hybrid search engine with fusion and scoring hyper-parameters."""
        self.client = client
        self.embedding_model = embedding_model
        self.top_k = top_k
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight
        self.rrf_k = rrf_k
        self.magic_phrase_boost = magic_phrase_boost
        self.bm25_k1 = bm25_k1
        self.bm25_b = bm25_b
        self.min_dense_score = min_dense_score

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        """Collapses whitespace and lowercases text for exact phrase matching."""
        return re.sub(r"\s+", " ", text.lower()).strip()

    @staticmethod
    def _stem_token(token: str) -> str:
        """Lightweight domain-aware stemmer to align legal morphological variants."""
        if len(token) <= 4 or token[0].isdigit():
            return token
        for suffix, replacement in (
            ("ification", "ify"),
            ("ization", "ize"),
            ("ation", "ate"),
            ("ments", "ment"),
            ("ilities", "ility"),
            ("ibility", "ible"),
            ("ability", "able"),
            ("liable", "liab"),
            ("liabil", "liab"),
            ("ingly", ""),
            ("edly", ""),
            ("ing", ""),
            ("ed", ""),
            ("es", ""),
            ("s", ""),
        ):
            if token.endswith(suffix) and len(token) - len(suffix) >= 3:
                return token[: -len(suffix)] + replacement
        return token

    @classmethod
    def tokenize(cls, text: str, include_stems: bool = True) -> list[str]:
        """Tokenizes contract text preserving percentages, numbers, and legal stems."""
        raw_tokens = cls._TOKEN_RE.findall(text.lower())
        tokens: list[str] = []
        for tok in raw_tokens:
            if tok in _STOPWORDS:
                continue
            tokens.append(tok)
            if include_stems:
                stemmed = cls._stem_token(tok)
                if stemmed != tok and stemmed not in _STOPWORDS:
                    tokens.append(f"#{stemmed}")
        return tokens

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """Computes cosine similarity between two dense float vectors."""
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return max(0.0, dot / (norm_a * norm_b))

    @classmethod
    def _build_rubric_query(cls, item: dict[str, Any]) -> str:
        """Constructs a rich semantic query string for a rubric requirement."""
        parts = [
            str(item.get("name", "")),
            str(item.get("description", "")),
            f"Target standard: {item.get('target_value', '')}",
        ]
        fallback = item.get("acceptable_fallback")
        if fallback:
            parts.append(f"Acceptable fallback: {fallback}")
        keywords = item.get("keywords") or []
        if keywords:
            parts.append("Keywords: " + ", ".join(str(k) for k in keywords))
        magic_phrases = item.get("magic_phrases") or []
        if magic_phrases:
            parts.append("Key phrases: " + ", ".join(str(p) for p in magic_phrases))
        return ". ".join(p for p in parts if p)

    def _compute_local_dense_vectors(
        self, texts: list[str]
    ) -> list[list[float]]:
        """Computes deterministic character n-gram + word-stem TF-IDF vectors as an offline dense fallback."""
        doc_features: list[dict[str, float]] = []
        df: Counter[str] = Counter()

        for text in texts:
            norm = self._normalize_whitespace(text)
            feats: dict[str, float] = {}
            # Word and stem features
            words = self.tokenize(norm, include_stems=True)
            for w in words:
                key = f"w:{w}"
                feats[key] = feats.get(key, 0.0) + 1.5
            # Word bigrams for local semantic phrase structure
            raw_words = [w for w in words if not w.startswith("#")]
            for i in range(len(raw_words) - 1):
                bg_key = f"bg:{raw_words[i]}_{raw_words[i + 1]}"
                feats[bg_key] = feats.get(bg_key, 0.0) + 2.0
            # Character 4-grams inside words to capture sub-word semantics
            for w in raw_words:
                if len(w) >= 4:
                    for i in range(len(w) - 3):
                        c4_key = f"c4:{w[i : i + 4]}"
                        feats[c4_key] = feats.get(c4_key, 0.0) + 0.5

            doc_features.append(feats)
            for feat in feats:
                df[feat] += 1

        vocab = sorted(df.keys())
        n_docs = max(1, len(texts))
        vectors: list[list[float]] = []

        for feats in doc_features:
            vec: list[float] = []
            for term in vocab:
                tf = feats.get(term, 0.0)
                if tf > 0.0:
                    idf = math.log(1.0 + (n_docs / df[term]))
                    vec.append((1.0 + math.log(tf)) * idf)
                else:
                    vec.append(0.0)
            vectors.append(vec)

        return vectors

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embeds texts using Gemini Embedding API, falling back to local dense vectors when offline."""
        if not texts:
            return []

        if self.client is not None:
            try:
                response = self.client.models.embed_content(
                    model=self.embedding_model,
                    contents=texts,
                )
                embeddings = getattr(response, "embeddings", None)
                if (
                    isinstance(embeddings, list)
                    and len(embeddings) == len(texts)
                    and all(
                        isinstance(getattr(e, "values", None), list)
                        and len(e.values) > 0
                        and isinstance(e.values[0], (int, float))
                        for e in embeddings
                    )
                ):
                    return [list(e.values) for e in embeddings]
            except (
                genai_errors.APIError,
                RuntimeError,
                ValueError,
                TypeError,
                AttributeError,
                OSError,
            ) as exc:
                logger.debug(
                    "Falling back to local dense vectors after embed_content error: %s",
                    exc,
                )

        return self._compute_local_dense_vectors(texts)

    def _score_sparse_all(
        self,
        clauses: list[ContractClause],
        rubric_items: list[dict[str, Any]],
    ) -> list[list[tuple[float, list[str], list[str]]]]:
        """Computes BM25 + legal 'magic phrase' sparse scores for every (rubric_item, clause) pair."""
        if not clauses:
            return [[] for _ in rubric_items]

        clause_texts = [
            f"{c.section_heading} {c.clause_title} {c.text}" for c in clauses
        ]
        norm_clause_texts = [self._normalize_whitespace(t) for t in clause_texts]
        tokenized_clauses = [
            self.tokenize(t, include_stems=True) for t in clause_texts
        ]
        doc_freqs = [Counter(tokens) for tokens in tokenized_clauses]
        doc_lens = [len(tokens) for tokens in tokenized_clauses]
        avg_dl = sum(doc_lens) / len(clauses) if clauses else 1.0

        # Inverse document frequency (BM25 Okapi)
        n_docs = len(clauses)
        df: Counter[str] = Counter()
        for freq_map in doc_freqs:
            for term in freq_map:
                df[term] += 1

        idf: dict[str, float] = {
            term: math.log(1.0 + (n_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

        all_item_scores: list[list[tuple[float, list[str], list[str]]]] = []
        for item in rubric_items:
            raw_keywords = [
                str(k).strip() for k in (item.get("keywords") or []) if str(k).strip()
            ]
            if not raw_keywords:
                fallback_text = f"{item.get('name', '')} {item.get('description', '')} {item.get('target_value', '')}"
                raw_keywords = self.tokenize(fallback_text, include_stems=False)

            magic_phrases = [
                self._normalize_whitespace(str(p))
                for p in (item.get("magic_phrases") or [])
                if str(p).strip()
            ]

            query_source = " ".join(
                [
                    str(item.get("name", "")),
                    str(item.get("description", "")),
                    " ".join(raw_keywords),
                    " ".join(magic_phrases),
                ]
            )
            query_tokens = list(
                dict.fromkeys(self.tokenize(query_source, include_stems=True))
            )

            item_clause_results: list[tuple[float, list[str], list[str]]] = []
            for idx, clause in enumerate(clauses):
                freq_map = doc_freqs[idx]
                dl = doc_lens[idx]
                norm_text = norm_clause_texts[idx]

                # 1. BM25 lexical score over query tokens and stems
                bm25_score = 0.0
                for q_tok in query_tokens:
                    tf = freq_map.get(q_tok, 0)
                    if tf > 0:
                        term_idf = idf.get(q_tok, 0.0)
                        denom = tf + self.bm25_k1 * (
                            1.0 - self.bm25_b + self.bm25_b * (dl / max(1.0, avg_dl))
                        )
                        bm25_score += term_idf * ((tf * (self.bm25_k1 + 1.0)) / denom)

                # 2. Exact keyword match tracking
                matched_kw: list[str] = []
                for kw in raw_keywords:
                    kw_norm = self._normalize_whitespace(kw)
                    if not kw_norm:
                        continue
                    kw_stem = f"#{self._stem_token(kw_norm)}"
                    if (
                        (
                            kw_norm in norm_text
                            or kw_norm in freq_map
                            or kw_stem in freq_map
                        )
                        and kw not in matched_kw
                    ):
                        matched_kw.append(kw)

                # 3. Exact "magic phrase" substring matching + boost
                matched_magic: list[str] = []
                for orig_phrase, norm_phrase in zip(
                    item.get("magic_phrases") or [], magic_phrases
                ):
                    if norm_phrase and norm_phrase in norm_text:
                        matched_magic.append(str(orig_phrase))

                # 4. In multi-tier hierarchies, detect contractual override magic phrases
                if clause.source_document and (bm25_score > 0.0 or matched_magic):
                    for ov_phrase in _OVERRIDE_MAGIC_PHRASES:
                        if ov_phrase in norm_text and ov_phrase not in matched_magic:
                            matched_magic.append(ov_phrase)

                total_sparse = bm25_score + (
                    len(matched_magic) * self.magic_phrase_boost
                )
                item_clause_results.append((total_sparse, matched_magic, matched_kw))

            all_item_scores.append(item_clause_results)

        return all_item_scores

    @staticmethod
    def _find_referenced_clause(
        ref_num: str,
        clauses: list[ContractClause],
        from_level: int = 0,
    ) -> ContractClause | None:
        """Recursively searches the current level and ancestor levels (L0 -> L1 -> Ln) for a referenced section."""
        target_exact = f"section {ref_num}".lower()
        target_prefix = f"section {ref_num}.".lower()

        # Prioritize clauses at the current or higher-numbered (ancestor/parent) precedence levels
        ordered_clauses = sorted(
            clauses,
            key=lambda c: (
                0 if c.precedence_level >= from_level else 1,
                abs(c.precedence_level - from_level),
            ),
        )
        for clause in ordered_clauses:
            cid = clause.clause_id.lower()
            heading = clause.section_heading.lower()
            if (
                cid == target_exact
                or cid.startswith(target_prefix)
                or heading.startswith((target_exact + ":", target_exact + " "))
            ):
                return clause
        return None

    def retrieve_for_rubric(
        self,
        clauses: list[ContractClause],
        rubric_items: list[dict[str, Any]],
    ) -> list[RubricRetrievalBundle]:
        """Executes hybrid dense + sparse retrieval with RRF fusion and recursive hierarchy resolution."""
        if not clauses:
            return [
                RubricRetrievalBundle(
                    item_id=str(item.get("id", "")),
                    item_name=str(item.get("name", "")),
                    query_text=self._build_rubric_query(item),
                )
                for item in rubric_items
            ]

        clause_repr_texts = [
            f"{c.qualified_id} {c.section_heading} {c.clause_title}: {c.text}"
            for c in clauses
        ]
        rubric_queries = [self._build_rubric_query(item) for item in rubric_items]

        # 1. Compute Dense Semantic Embeddings in one combined batch for shared vector space
        combined_embeddings = self._embed_texts(clause_repr_texts + rubric_queries)
        clause_embeddings = combined_embeddings[: len(clauses)]
        query_embeddings = combined_embeddings[len(clauses) :]

        # 2. Compute Sparse (BM25 + Magic Phrases) Scores
        sparse_matrix = self._score_sparse_all(clauses, rubric_items)

        # 3. Fuse Dense + Sparse Rankings via Reciprocal Rank Fusion (RRF)
        bundles: list[RubricRetrievalBundle] = []
        for item_idx, item in enumerate(rubric_items):
            q_emb = query_embeddings[item_idx]
            dense_scores = [
                self._cosine_similarity(q_emb, c_emb) for c_emb in clause_embeddings
            ]
            sparse_entries = sparse_matrix[item_idx]

            # Dense ranks (1-indexed, sorted descending by dense_score)
            dense_order = sorted(
                range(len(clauses)),
                key=lambda i: dense_scores[i],
                reverse=True,
            )
            dense_ranks: dict[int, int] = {
                clause_i: rank + 1
                for rank, clause_i in enumerate(dense_order)
                if dense_scores[clause_i] > 0.0
            }

            # Sparse ranks (1-indexed, only for clauses with positive sparse score)
            positive_sparse_indices = [
                i for i, (s_score, _, _) in enumerate(sparse_entries) if s_score > 0.0
            ]
            sparse_order = sorted(
                positive_sparse_indices,
                key=lambda i: sparse_entries[i][0],
                reverse=True,
            )
            sparse_ranks: dict[int, int] = {
                clause_i: rank + 1 for rank, clause_i in enumerate(sparse_order)
            }

            candidates: list[ClauseMatch] = []
            for c_idx, clause in enumerate(clauses):
                d_score = dense_scores[c_idx]
                s_score, matched_magic, matched_kw = sparse_entries[c_idx]
                d_rank = dense_ranks.get(c_idx)
                s_rank = sparse_ranks.get(c_idx)

                # Filter out completely unaligned noise clauses
                if s_score <= 0.0 and d_score < self.min_dense_score:
                    continue

                rrf_val = 0.0
                if d_rank is not None and d_score >= self.min_dense_score:
                    rrf_val += self.dense_weight / (self.rrf_k + d_rank)
                if s_rank is not None:
                    rrf_val += self.sparse_weight / (self.rrf_k + s_rank)

                # Direct tie-breaking boost for exact contractual "magic words"
                if matched_magic:
                    rrf_val += 0.005 * len(matched_magic)

                # In multi-document hierarchies, favor higher-precedence tiers (L0 > L1 > L2) on relevant matches
                if clause.source_document and s_score > 0.0:
                    rrf_val += 0.002 / (1.0 + clause.precedence_level)

                if rrf_val > 0.0:
                    candidates.append(
                        ClauseMatch(
                            clause=clause,
                            rrf_score=round(rrf_val, 6),
                            dense_score=round(d_score, 4),
                            sparse_score=round(s_score, 4),
                            dense_rank=d_rank,
                            sparse_rank=s_rank,
                            matched_magic_phrases=matched_magic,
                            matched_keywords=matched_kw,
                        )
                    )

            # Sort candidates by RRF score descending, then precedence_level ascending, then sparse_score
            candidates.sort(
                key=lambda m: (
                    m.rrf_score,
                    -m.clause.precedence_level,
                    m.sparse_score,
                    m.dense_score,
                ),
                reverse=True,
            )
            top_matches = candidates[: self.top_k]
            included_ids = {m.clause.qualified_id for m in top_matches}

            # 4. Down-chain Amendment Detection: attach child clauses (L_child < L_match) that explicitly amend the primary matched section
            amending_matches: list[ClauseMatch] = []
            if top_matches:
                primary_match = top_matches[0]
                primary_sec_num = re.sub(
                    r"^(?:Section|Article|Clause)\s+",
                    "",
                    primary_match.clause.clause_id,
                    flags=re.IGNORECASE,
                ).strip()
                for c_idx, clause in enumerate(clauses):
                    if clause.qualified_id in included_ids:
                        continue
                    if (
                        primary_sec_num in clause.referenced_sections
                        and clause.precedence_level
                        < primary_match.clause.precedence_level
                    ):
                        s_score, matched_magic, matched_kw = sparse_entries[c_idx]
                        included_ids.add(clause.qualified_id)
                        amending_matches.append(
                            ClauseMatch(
                                clause=clause,
                                rrf_score=round(primary_match.rrf_score + 0.001, 6),
                                dense_score=round(dense_scores[c_idx], 4),
                                sparse_score=round(s_score, 4),
                                dense_rank=dense_ranks.get(c_idx),
                                sparse_rank=sparse_ranks.get(c_idx),
                                matched_magic_phrases=matched_magic,
                                matched_keywords=matched_kw,
                            )
                        )

            combined_primary = amending_matches + top_matches

            # 5. Up-chain Cross-Reference Resolution: search current & ancestor documents (L0 -> L1 -> Ln)
            missing_refs: list[str] = []
            cross_ref_matches: list[ClauseMatch] = []

            for match in combined_primary:
                for ref_num in match.clause.referenced_sections:
                    ref_clause = self._find_referenced_clause(
                        ref_num,
                        clauses,
                        from_level=match.clause.precedence_level,
                    )
                    if ref_clause is not None:
                        if ref_clause.qualified_id not in included_ids:
                            included_ids.add(ref_clause.qualified_id)
                            cross_ref_matches.append(
                                ClauseMatch(
                                    clause=ref_clause,
                                    rrf_score=0.0,
                                    dense_score=0.0,
                                    sparse_score=0.0,
                                    dense_rank=None,
                                    sparse_rank=None,
                                    is_cross_reference=True,
                                )
                            )
                    else:
                        ref_label = f"Section {ref_num}"
                        if ref_label not in missing_refs:
                            missing_refs.append(ref_label)

            bundles.append(
                RubricRetrievalBundle(
                    item_id=str(item.get("id", "")),
                    item_name=str(item.get("name", "")),
                    query_text=rubric_queries[item_idx],
                    matches=combined_primary + cross_ref_matches,
                    missing_cross_references=missing_refs,
                )
            )

        return bundles
