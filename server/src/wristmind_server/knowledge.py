from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import pytesseract
from PIL import Image
from pypdf import PdfReader
from .search_documents import query_numbers
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .config import Settings
from .db_models import KnowledgeChunk, KnowledgeSource
from .providers import ProviderError, ProviderRouter


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    pages: int
    kind: str
    # Text split by original PDF pages.  It lets ingestion retain a reliable
    # source-page reference even when one page needs several retrieval chunks.
    page_texts: tuple[str, ...] | None = None


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def normalize_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_ocr(path: Path, media_type: str, max_pdf_pages: int) -> ExtractedDocument:
    if media_type == "application/pdf" or path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        if len(reader.pages) > max_pdf_pages:
            raise ValueError(f"PDF has more than {max_pdf_pages} pages")
        page_texts = tuple(normalize_text(page.extract_text() or "") for page in reader.pages)
        pages = []
        for index, value in enumerate(page_texts, start=1):
            if value:
                pages.append(f"## Страница {index}\n\n{value}")
        if not pages:
            raise ValueError("PDF contains no extractable text; use VISION mode")
        return ExtractedDocument("\n\n".join(pages), len(reader.pages), "pdf", page_texts)
    image = Image.open(path)
    text = normalize_text(pytesseract.image_to_string(image, lang="rus+eng"))
    if not text:
        raise ValueError("No text recognized in image")
    return ExtractedDocument(text, 1, "image", (text,))


async def extract_document(
    path: Path,
    media_type: str,
    processing_mode: str,
    provider: ProviderRouter,
    settings: Settings,
) -> ExtractedDocument:
    from .feature_capabilities import enabled
    if not enabled(settings, 'digitization'): raise ValueError('Оцифровка отключена в настройках сервера')
    if processing_mode == "WEB":
        text = normalize_text(path.read_text(encoding="utf-8"))
        if not text:
            raise ValueError("Web source contains no readable text")
        return ExtractedDocument(text, 1, "web", (text,))
    if processing_mode == "VISION":
        try:
            text = normalize_text(await provider.analyze_file(path, media_type))
            pages = len(PdfReader(str(path)).pages) if path.suffix.lower() == ".pdf" else 1
            return ExtractedDocument(text, pages, "vision")
        except ProviderError:
            if not settings.mock_providers:
                raise
    return extract_ocr(path, media_type, settings.max_pdf_pages)


def _chunk_text(text: str, target_chars: int) -> list[str]:
    blocks = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for block in blocks:
        if current and current_size + len(block) > target_chars:
            chunks.append("\n\n".join(current))
            current = []
            current_size = 0
        current.append(block)
        current_size += len(block) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks or [text]


def chunk_document_with_pages(
    document: ExtractedDocument, target_chars: int = 4_000
) -> list[tuple[str, int | None, int | None]]:
    """Split a document for retrieval while preserving known PDF page boundaries."""
    if document.page_texts is None:
        return [(content, None, None) for content in _chunk_text(document.text, target_chars)]

    chunks: list[tuple[str, int | None, int | None]] = []
    for page_number, page_text in enumerate(document.page_texts, start=1):
        if not page_text:
            continue
        chunks.extend(
            (content, page_number, page_number)
            for content in _chunk_text(page_text, target_chars)
        )
    return chunks or [(document.text, None, None)]


def chunk_document(document: ExtractedDocument, target_chars: int = 4_000) -> list[str]:
    """Backward-compatible text-only chunk list for retrieval callers."""
    return [content for content, _, _ in chunk_document_with_pages(document, target_chars)]


def cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right): return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(item * item for item in left)) or 1.0
    right_norm = math.sqrt(sum(item * item for item in right)) or 1.0
    return dot / (left_norm * right_norm)


def lexical_score(query: str, content: str) -> float:
    terms = set(re.findall(r"[\w-]{2,}", query.lower()))
    if not terms:
        return 0.0
    content_terms = set(re.findall(r"[\w-]{2,}", content.lower()))
    return len(terms & content_terms) / len(terms)


# How much an exact numeric identifier is worth in the ranking. The score is
# ``semantic * 0.75 + lexical * 0.25``, so this is a strong tie-breaker.
NUMBER_IDENTIFIER_BONUS = 0.25


def context_fragment(chunk: KnowledgeChunk) -> str:
    source = chunk.source
    source_type = "VISION: описание изображения или документа" if source.processing_mode == "VISION" else "OCR: распознанный текст"
    return (
        f'<knowledge_fragment source="{source.title}" type="{source_type}">\n'
        f"{chunk.content}\n"
        "</knowledge_fragment>"
    )


async def knowledge_context(
    session: AsyncSession,
    mode_id: str,
    query: str,
    provider: ProviderRouter,
    settings: Settings,
    chat_id: str | None = None,
    exclude_source_ids: set[str] | None = None,
) -> tuple[str | None, dict[str, object]]:
    """Build the answer context.

    ``exclude_source_ids`` keeps documents the user rejected for the current
    search task out of this turn's candidates. They stay stored and readable
    everywhere else: exclusion is per task, never a deletion and never a verdict
    about the document itself.
    """
    from .feature_capabilities import enabled
    if not enabled(settings, 'rag'): return None, {'strategy':'disabled', 'reason':'RAG отключён в настройках сервера'}
    excluded = {str(item) for item in (exclude_source_ids or set()) if item}
    chunks = (
        await session.scalars(
            select(KnowledgeChunk)
            .options(selectinload(KnowledgeChunk.source))
            .join(KnowledgeSource)
            .where(
                KnowledgeSource.mode_id == mode_id,
                or_(KnowledgeSource.chat_id.is_(None), KnowledgeSource.chat_id == chat_id)
                if chat_id is not None else KnowledgeSource.chat_id.is_(None),
                KnowledgeSource.status == "ready",
                KnowledgeSource.deleted_at.is_(None),
                KnowledgeSource.id.notin_(excluded) if excluded else True,
            )
            .order_by(KnowledgeSource.created_at, KnowledgeChunk.ordinal)
        )
    ).all()
    chat_sources = {
        item.source.id: item.source.title
        for item in chunks
        if chat_id is not None and item.source.chat_id == chat_id
    }
    chat_source_meta: dict[str, object] = {}
    if chat_id is not None:
        chat_source_meta = {
            "chat_source_count": len(chat_sources),
            "chat_source_titles": list(chat_sources.values()),
        }
    if not chunks:
        return None, {
            "strategy": "none", "source_tokens": 0, "context_tokens": 0, **chat_source_meta,
        }
    total = sum(item.token_count for item in chunks)
    # Working Sources are collected automatically and can accumulate during a
    # long chat.  Rank them even below the normal full-context threshold so a
    # random old page does not crowd out the material relevant to this turn.
    has_working_sources = any(
        item.source.source_tier == "working" and item.source.chat_id == chat_id
        for item in chunks
    )
    # The chat's own material has a larger ceiling than the shared base, so a
    # big saved document is not squeezed out by unrelated mode sources.
    budget_limit = (
        settings.chat_source_context_budget_tokens
        if has_working_sources
        else settings.retrieval_context_budget_tokens
    )
    if total <= settings.full_context_threshold_tokens and not has_working_sources:
        context = "\n\n".join(context_fragment(item) for item in chunks)
        return context, {
            "strategy": "full", "source_tokens": total, "context_tokens": total, **chat_source_meta,
        }

    # Working Sources belong to this chat, and the chat is usually about them.
    # When they all fit in the retrieval budget they are pinned in full, in
    # document order, before the ranked fill: that is what lets an answer read
    # the entire saved text (for example "write an essay based on this text").
    # Nothing is added on top of the existing budget, so the prompt never grows;
    # when the material does not fit, ranking is kept unchanged.
    pinned: list[KnowledgeChunk] = []
    pinned_tokens = 0
    if settings.full_working_source_context and has_working_sources:
        candidates = [
            item for item in chunks
            if item.source.source_tier == "working" and item.source.chat_id == chat_id
        ]
        candidate_tokens = sum(item.token_count for item in candidates)
        if candidates and candidate_tokens <= budget_limit:
            pinned = candidates
            pinned_tokens = candidate_tokens
    pinned_source_count = len({item.source.id for item in pinned})
    # Reported only when something was actually pinned, so every existing shape
    # of the metadata stays exactly as it was.
    pinned_meta: dict[str, object] = (
        {"full_source_count": pinned_source_count, "full_source_tokens": pinned_tokens}
        if pinned else {}
    )
    if pinned and (pinned_tokens >= budget_limit or len(pinned) == len(chunks)):
        # Every useful chunk is already selected; semantic ranking cannot change the result.
        context = "\n\n".join(context_fragment(item) for item in pinned)
        return context, {
            "strategy": "full_sources",
            "source_tokens": total,
            "context_tokens": pinned_tokens,
            **pinned_meta,
            **chat_source_meta,
        }

    pinned_ids = {item.id for item in pinned}
    query_vector = (await provider.embed([query]))[0]
    # A named identifier ("задача 12") is not interchangeable with its word, so a
    # chunk that carries the exact identifier outranks a slightly closer
    # semantic neighbour. No model call: the check is textual.
    named_numbers = query_numbers(query)
    number_patterns = [
        re.compile(
            r"(?:задача|задание|глава|раздел|пункт|task|problem|chapter|section)"
            r"\s*(?:№\s*)?" + re.escape(number) + r"\b"
        )
        for number in named_numbers
    ]
    scored = []
    for item in chunks:
        if item.id in pinned_ids:
            continue
        embedding = list(item.embedding or [])
        semantic = cosine(query_vector, embedding) if embedding else 0.0
        score = semantic * 0.75 + lexical_score(query, item.content) * 0.25
        if number_patterns:
            content = item.content.casefold()
            if any(pattern.search(content) for pattern in number_patterns):
                score += NUMBER_IDENTIFIER_BONUS
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    selected: list[KnowledgeChunk] = list(pinned)
    budget = pinned_tokens
    for _, item in scored:
        if selected and budget + item.token_count > budget_limit:
            continue
        selected.append(item)
        budget += item.token_count
        if budget >= budget_limit:
            break
    context = "\n\n".join(context_fragment(item) for item in selected)
    return context, {
        "strategy": "full_sources" if pinned else "hybrid",
        "source_tokens": total,
        "context_tokens": budget,
        **pinned_meta,
        **chat_source_meta,
    }
