"""Cheap, transparent candidate ranking; signals are preferences, never a whitelist."""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse
from .search_documents import query_numbers, _identifier_pattern

_STOP = set('найди найти полный оригинальный текст проверь наличие всех глав глава раздел документ повесть произведение источник compare find full original text chapter section'.split())
_BAD = re.compile(r'пересказ|кратк\w* содержан|готов\w* ответ|гдз|решебник|summary|study guide', re.I)
_FULL = re.compile(r'полн\w* текст|текст целиком|оригинал|первоисточник|full text|original text', re.I)
_MULTI = re.compile(r'сравн|противореч|нескольк\w* источ|разн\w* источ|сопостав|compare|cross.check', re.I)
_COMPLETE = re.compile(r'полнот|вс[еех]+\s+\d*\s*глав|наличие\s+(?:всех\s+)?\d+\s+глав|все раздел|completeness|all chapters', re.I)
_SECONDARY = re.compile(r'комментари\w*|пособие\s+для\s+учител\w*|литературовед\w*|кратк\w*\s+содержан\w*|пересказ|study guide', re.I)


def primary_document_requested(query):
    return bool(_FULL.search(query) or completeness_requested(query))


def secondary_material(title, text=''):
    """Use the document's front matter, never incidental notes deep in an original."""
    return bool(_SECONDARY.search(title) or re.search(
        r'(?im)^\s*(?:#{1,6}\s*)?(?:комментарий|пособие для учителя|краткое содержание|пересказ)\s*[.\n]|'
        r'комментарий\.\s*пособие для учителя', text[:2400]))


def additional_document_task(query):
    """A structure check cannot also satisfy a subsequent analysis/excerpt task."""
    return bool(re.search(r'затем|после\s+(?:этого|проверки)|\b(?:эпизод|цитат|проанализ|охарактериз|выдели|подбери|составь)\w*', query, re.I))


def normalized(value):
    return ' '.join(re.findall(r'\w+', value.casefold().replace('ё', 'е')))


def author_stems(query):
    # An explicit initials + surname form; short initials alone are not evidence.
    return [normalized(x)[:6] for x in re.findall(r"(?:[А-ЯA-Z]\.\s*){1,3}([А-ЯA-Z][а-яa-zё-]+)", query)]


def exact_titles(query):
    return [normalized(x) for x in re.findall(r'[«"“](.*?)[»"”]', query) if len(normalized(x)) >= 4]


@dataclass(frozen=True)
class RankedCandidate:
    score: float
    reasons: tuple[str, ...]
    exact: bool
    full: bool
    undesirable: bool
    query_coverage: float


def rank_candidate(query, item):
    title = normalized(item.title)
    value = normalized(item.title + ' ' + item.snippet)
    terms = {x[:5] for x in normalized(query).split() if len(x) > 2 and x not in _STOP}
    words = value.split()
    title_words = title.split()
    coverage = sum(any(w.startswith(t) for w in words) for t in terms) / max(1, len(terms))
    title_coverage = sum(any(w.startswith(t) for w in title_words) for t in terms) / max(1, len(terms))
    score = 4 * coverage + 4 * title_coverage
    reasons = [f'query_match={coverage:.2f}', f'title_match={title_coverage:.2f}']
    titles = exact_titles(query)
    authors = author_stems(query)
    author_match = all(any(w.startswith(author) for w in words) for author in authors)
    exact = bool(titles) and all(x in title for x in titles) and author_match
    if authors:
        score += 2 if author_match else -4
        reasons.append("author_match" if author_match else "author_not_confirmed")
    if titles:
        score += 6 if exact else -5
        reasons.append('exact_title' if exact else 'title_not_confirmed')
    full = bool(_FULL.search(item.title + ' ' + item.snippet))
    undesirable = bool(_BAD.search(item.title + ' ' + item.snippet)) and not bool(_BAD.search(query))
    if primary_document_requested(query) and secondary_material(item.title, item.snippet):
        undesirable = True
        reasons.append('secondary_not_original')
    if full:
        score += 3
        reasons.append('full_original_label')
    if undesirable:
        score -= 10
        reasons.append('summary_or_answers')
    for number in query_numbers(query):
        if _identifier_pattern(number).search(item.title + ' ' + item.snippet):
            score += 3
            reasons.append('section_number')
    parsed = urlparse(item.url)
    host = (parsed.hostname or '').casefold()
    # Generic institution and source-type clues, not trusted-domain membership.
    if host.endswith(('.gov', '.edu', '.gov.ru', '.ac.uk')):
        score += 1
        reasons.append('institution_domain')
    if re.search(r'официальн|библиотек|издатель|official|library|publisher', value):
        score += 1
        reasons.append('primary_source_type')
    return RankedCandidate(score, tuple(reasons), exact, full, undesirable, coverage)


def rank_results(query, results):
    # Stable ties retain SearXNG's own ordering; candidates are never removed.
    return sorted(results, key=lambda x: rank_candidate(query, x).score, reverse=True)


def obvious_source(query, results, attempted):
    if _MULTI.search(query):
        return None
    ranked = sorted(((key, rank_candidate(query, item)) for key, item in results.items()
                     if key not in attempted), key=lambda pair: pair[1].score, reverse=True)
    if not ranked:
        return None
    key, best = ranked[0]
    margin = best.score - ranked[1][1].score if len(ranked) > 1 else best.score
    return key if best.exact and best.full and not best.undesirable and best.score >= 10 and margin >= 3 else None


def comparison_requested(query):
    return bool(_MULTI.search(query))


def completeness_requested(query):
    return bool(_COMPLETE.search(query))


def document_check(query, title, text):
    """Check explicit numbered coverage. Heading presence is not textual authenticity."""
    if primary_document_requested(query) and secondary_material(title, text):
        return {'kind': 'primary_source', 'verified': False, 'reason': 'secondary_not_original'}
    titles = exact_titles(query)
    identity_text = normalized(title + ' ' + text[:2000])
    identity = (not titles or all(x in identity_text for x in titles)) and all(
        any(word.startswith(author) for word in identity_text.split()) for author in author_stems(query))
    count = re.search(r'\b(\d{1,3})\s+глав', query, re.I)
    if completeness_requested(query):
        expected = int(count[1]) if count else None
        if not expected or expected > 200:
            return {'kind': 'completeness', 'verified': False, 'reason': 'expected_sections_unknown'}
        # Require separate section headings, not a contents list. A chapter must
        # have at least 80 characters of body before the following heading.
        headings = list(re.finditer(r'(?im)^\s*(?:#{1,6}\s*)?(?:глава|chapter)\s+(\d{1,3}|[IVXLCDM]+)\b[^\n]*\n', text))
        found = set()
        for index, match in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            if len(text[match.end():end].strip()) >= 80:
                for number in range(1, expected + 1):
                    if _identifier_pattern(str(number)).search(match[0]):
                        found.add(number)
                        break
        missing = sorted(set(range(1, expected + 1)) - found)
        return {'kind': 'completeness', 'verified': identity and not missing,
                'expected': expected, 'found': sorted(found), 'missing': missing,
                'scope': 'section_headings_and_body_presence_only'}
    numbers = query_numbers(query)
    if numbers:
        headings = list(re.finditer(
            r'(?im)^\s*(?:#{1,6}\s*)?(?:глава|chapter|раздел|section|пункт)\s+\d+\b[^\n]*\n', text))
        found = set()
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            if len(text[heading.end():end].strip()) >= 10:
                found.update(number for number in numbers if _identifier_pattern(number).search(heading[0]))
        return {'kind': 'section', 'verified': identity and len(found) == len(numbers),
                'found': sorted(found), 'scope': 'section_heading_and_body_presence_only'}
    return {'kind': 'general', 'verified': False}


def self_contained_source_query(query):
    """Explicit title + purpose need no contextual query-rewriting call."""
    return bool(exact_titles(query) and (_FULL.search(query) or query_numbers(query))) and not bool(
        re.search(r'\b(?:эт\w*|тот|ту|того|прежн\w*|друг\w*|выше|вместо)\b', query, re.I))


def specific_section_requested(query):
    return bool(query_numbers(query) and re.search(r'глав\w*|раздел\w*|пункт\w*|chapter|section', query, re.I))
