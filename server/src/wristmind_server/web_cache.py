"""Lazy, bounded public-page cache. Original provenance and user files are immutable."""
from datetime import datetime, timezone
import hashlib
import re
from urllib.parse import urlparse
from sqlalchemy import select, func
from .config import get_settings
from .db_models import RawWebSource, KnowledgeSource
from .web_search import HTML_EXTRACTION_VERSION
from . import search_trace


def document_text(row: RawWebSource) -> str:
    return row.full_content if row.full_content is not None else row.content


def material_kind(title: str, url: str, text: str) -> str:
    path = urlparse(url).path.casefold()
    if re.search(r'новост|news|сегодня|breaking', title.casefold() + ' ' + path):
        return 'news'
    if re.search(r'полн\w* текст|оригинал|повесть|роман|full text', title, re.I) and (
        len(text) > 5000 and len(re.findall(r'(?im)^\s*(?:#+\s*)?(?:глава|chapter)\b', text)) >= 3
    ):
        return 'static'
    if path.endswith('.pdf') or text.startswith('## Страница '):
        return 'document'
    return 'page'


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def cache_decision(row, *, fresh=False, now=None, settings=None):
    config = settings or get_settings()
    if row is None:
        return 'missing'
    if fresh:
        return 'fresh_required'
    if row.extraction_version != HTML_EXTRACTION_VERSION:
        return 'legacy_extraction'
    if not document_text(row).strip():
        return 'empty'
    now = now or datetime.now(timezone.utc)
    checked = row.last_checked_at or row.retrieved_at
    if checked is None:
        return 'unknown_age'
    kind = row.cache_kind or material_kind(row.title, row.url, document_text(row))
    ttl = {'news': config.web_cache_news_ttl_seconds, 'static': config.web_cache_static_ttl_seconds,
           'document': config.web_cache_document_ttl_seconds}.get(kind, config.web_cache_page_ttl_seconds)
    age = (aware(now) - aware(checked)).total_seconds()
    if age < -300 or age >= ttl:
        return 'expired'
    return 'hit'


def reusable_document(row: RawWebSource | None, *, fresh: bool, max_html_chars: int,
                      now=None, settings=None) -> str | None:
    reason = cache_decision(row, fresh=fresh, now=now, settings=settings)
    if reason == 'hit':
        text = document_text(row)
        if len(text) > max_html_chars and not text.startswith('## Страница '):
            reason = 'document_limit'
    trace = search_trace.current()
    if trace is not None:
        if reason == 'hit': trace.cache_hits += 1
        else: trace.cache_misses += 1
        trace.event('CACHE', reason=reason, status='hit' if reason == 'hit' else 'miss')
    if reason != 'hit':
        return None
    # Reads must stay read-only while independent job-event sessions write.
    # The worker records access in its final cache transaction.
    return text


async def cache_document(session, chat_id: str, title: str, url: str, text: str,
                         *, protect: bool = False, refreshed: bool = True, now=None, settings=None) -> RawWebSource | None:
    config = settings or get_settings()
    now = now or datetime.now(timezone.utc)
    row = await session.scalar(select(RawWebSource).where(
        RawWebSource.chat_id == chat_id, RawWebSource.url == url))
    if row is not None and not protect:
        protect = bool(await session.scalar(select(KnowledgeSource.id).where(
            KnowledgeSource.raw_source_id == row.id).limit(1)))
    if row is None:
        required_bytes = len(text.encode('utf-8'))
    else:
        # Original snapshot/hash/offset provenance are never overwritten.
        required_bytes = len(row.content.encode('utf-8')) + (
            len(text.encode('utf-8')) if row.content != text else 0)
    if not protect:
        # Metadata-only aggregate, not a scan/materialisation of document bodies.
        # Unknown legacy sizes reserve the worst supported HTML size until lazy access.
        unprotected = ~select(KnowledgeSource.id).where(KnowledgeSource.raw_source_id == RawWebSource.id).exists()
        count, occupied = (await session.execute(select(func.count(RawWebSource.id),
            func.coalesce(func.sum(func.coalesce(RawWebSource.cache_bytes, config.web_html_max_document_chars * 4)), 0))
            .where(unprotected))).one()
        previous_bytes = (row.cache_bytes if row.cache_bytes is not None else config.web_html_max_document_chars * 4) if row else 0
        if (row is None and count >= config.web_cache_max_entries) or (
            occupied - previous_bytes + required_bytes > config.web_cache_max_bytes and (row is None or required_bytes > previous_bytes)
        ):
            trace = search_trace.current()
            if trace is not None: trace.cache_skipped += 1
            search_trace.event('CACHE', status='skipped', reason='admission_limit', cache_bytes=occupied)
            return row  # Existing snapshot remains usable until expiry; no fabricated refresh time.
    if row is None:
        row = RawWebSource(chat_id=chat_id, url=url, title=title[:240], content=text,
                           content_hash=hashlib.sha256(text.encode()).hexdigest(),
                           extraction_version=HTML_EXTRACTION_VERSION, retrieved_at=now)
        session.add(row)
    else:
        row.full_content = text if row.content != text else None
        row.title = title[:240]
        row.extraction_version = HTML_EXTRACTION_VERSION
    if refreshed:
        row.last_checked_at = now
    elif row.last_checked_at is None:
        row.last_checked_at = row.retrieved_at or now
    row.last_accessed_at = now
    row.cache_kind = material_kind(title, url, text)
    row.cache_bytes = required_bytes
    await session.flush()
    search_trace.event('CACHE', status='stored', kind=row.cache_kind, cache_bytes=required_bytes,
                       reason='protected_source' if protect else 'admitted')
    return row
