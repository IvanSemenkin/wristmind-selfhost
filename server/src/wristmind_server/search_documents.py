"""Bounded document views with offsets into the unchanged original text."""
from __future__ import annotations

from dataclasses import dataclass
import re
import math


@dataclass(frozen=True)
class TextBlock:
    id: int
    start: int
    end: int
    page: int | None


def query_numbers(query: str) -> set[str]:
    """Numeric identifiers the query names: "задача 12", "№ 7", "глава 3".

    A numeric identifier is not interchangeable with its word ("задача" alone),
    so both the lexical document search and the chunk ranking use this set.
    """
    numbers = set(re.findall(
        r"(?:задач\w*|задан\w*|глав\w*|раздел\w*|пункт\w*|task|problem|chapter|section)"
        r"\s*(?:№|номер)?\s*(\d{1,4})\b", query.casefold(),
    ))
    numbers.update(re.findall(r"№\s*(\d{1,4})\b", query))
    if query.strip().isdigit():
        numbers.add(query.strip())
    for stem, number in (("перв", "1"), ("втор", "2"), ("треть", "3")):
        if re.search(stem + r"\w*\s+(?:задач|задан|глав|раздел|пункт)", query.casefold()):
            numbers.add(number)
    return numbers


def _identifier_pattern(number: str):
    # Chapters in literary originals commonly use Roman numerals.
    value = int(number)
    roman = ""
    if 0 < value < 4000:
        for amount, token in ((1000,"m"),(900,"cm"),(500,"d"),(400,"cd"),
                              (100,"c"),(90,"xc"),(50,"l"),(40,"xl"),
                              (10,"x"),(9,"ix"),(5,"v"),(4,"iv"),(1,"i")):
            count, value = divmod(value, amount)
            roman += token * count
    alternatives = re.escape(number) + ("|" + roman if roman else "")
    return re.compile(r"(?:задача|задание|глава|раздел|пункт|task|problem|chapter|section)"
                      r"\s*(?:№\s*)?(?:" + alternatives + r")\b", re.IGNORECASE)


class DocumentView:
    def __init__(self, text: str):
        self.text = text
        self.blocks: list[TextBlock] = []
        headings = list(re.finditer(r"(?m)^## Страница (\d+)\s*$", text))
        regions = [(m.start(), headings[i + 1].start() if i + 1 < len(headings) else len(text),
                    int(m.group(1))) for i, m in enumerate(headings)]
        if not regions:
            regions = [(0, len(text), None)]
        elif regions[0][0]:
            regions.insert(0, (0, regions[0][0], None))
        for start, end, page in regions:
            while start < end:
                stop = min(start + 1400, end)
                if stop < end:
                    boundary = text.rfind("\n", start + 700, stop)
                    if boundary < 0:
                        boundary = text.rfind(" ", start + 700, stop)
                    if boundary >= 0:
                        stop = boundary + 1
                self.blocks.append(TextBlock(len(self.blocks), start, stop, page))
                start = stop

    def read(self, start: int, end: int, *, max_chars: int | None = None) -> str:
        if not 0 <= start <= end < len(self.blocks):
            raise ValueError("Invalid document boundaries")
        begin, stop = self.blocks[start].start, self.blocks[end].end
        if max_chars is not None and stop - begin > max_chars:
            raise ValueError("Read a smaller block range")
        return self.text[begin:stop]

    def scores(self, query: str) -> list[tuple[float, int]]:
        """Per-block relevance scores for this query, best first.

        Exposed so a caller can compare whole documents before reading one of
        them: the same lexical scoring with the numeric-identifier boost decides
        which saved source is worth showing a window from.
        """
        # Prefix matching covers common Russian inflections; the model remains
        # responsible for semantic selection and can issue another query.
        terms = list(dict.fromkeys(word[:5] for word in re.findall(r"\w+", query.casefold()) if len(word) >= 4))[:32]
        numbers = query_numbers(query)
        patterns = [_identifier_pattern(number) for number in numbers]
        counts = []
        for block in self.blocks:
            words = re.findall(r"\w+", self.text[block.start:block.end].casefold())
            counts.append({term: min(3, sum(word.startswith(term) for word in words)) for term in terms})
        frequencies = {term: sum(bool(count[term]) for count in counts) for term in terms}
        scored = []
        for block, count in zip(self.blocks, counts):
            score = sum(value * math.log(1 + len(self.blocks) / max(1, frequencies[term]))
                        for term, value in count.items())
            text = self.text[block.start:block.end].casefold()
            for pattern in patterns:
                if pattern.search(text):
                    score += 20
            if score:
                scored.append((score, block.id))
        if patterns:
            matching = {index for score, index in scored if any(
                pattern.search(self.text[self.blocks[index].start:self.blocks[index].end])
                for pattern in patterns
            )}
            scored = [(score, index) for score, index in scored if index in matching]
        return sorted(scored, key=lambda item: (-item[0], item[1]))

    def best_score(self, query: str) -> float:
        """Highest block score for this query, 0.0 when nothing matched."""
        scored = self.scores(query)
        return scored[0][0] if scored else 0.0

    def find(self, query: str, *, limit: int = 9) -> list[TextBlock]:
        best = [index for _, index in self.scores(query)[:2]]
        if query_numbers(query) and not best:
            return []
        # Relevant blocks precede neighbours, so a small model budget never
        # consumes its space on earlier chapters before showing the actual hit.
        ids = list(best)
        for distance in range(1, 5):
            for index in best:
                for adjacent in (index - distance, index + distance):
                    if 0 <= adjacent < len(self.blocks) and adjacent not in ids:
                        ids.append(adjacent)
        if not ids:
            # Distribute the fallback across the document, rather than treating
            # a cover/title page as proof that the whole document is irrelevant.
            ids = sorted({round(i * (len(self.blocks) - 1) / 2) for i in range(3)}) if self.blocks else []
        return [self.blocks[index] for index in ids[:limit]]

    def prompt(self, query: str, *, limit: int = 9, max_chars: int = 12_000) -> str:
        fragments = []
        used = 0
        for block in self.find(query, limit=limit):
            fragment = f"[block {block.id}; page {block.page or '-'}]\n{self.text[block.start:block.end]}"
            if used + len(fragment) + 2 > max_chars:
                break
            fragments.append(fragment)
            used += len(fragment) + 2
        return "\n\n".join(fragments) or "По этому запросу совпадений в извлечённом тексте не найдено; это не доказывает отсутствие раздела в оригинале."

    def numbered_lines(self, query: str, *, max_chars: int = 12_000) -> tuple[str, dict[int, tuple[int, int]]]:
        selected = self.find(query, limit=max(1, min(9, max_chars // 1500)))
        offsets = {}
        lines = []
        start = 0
        source_lines = []
        for original in self.text.splitlines(keepends=True):
            while len(original) > 700:
                cut = original.rfind(" ", 350, 700)
                cut = cut + 1 if cut >= 0 else 700
                source_lines.append(original[:cut])
                original = original[cut:]
            source_lines.append(original)
        for number, line in enumerate(source_lines):
            end = start + len(line)
            if any(start < block.end and end > block.start for block in selected):
                rendered = f"[line {number}] {line.rstrip()}"
                if sum(len(item) + 1 for item in lines) + len(rendered) > max_chars:
                    break
                offsets[number] = (start, end)
                lines.append(rendered)
            start = end
        return "\n".join(lines), offsets


def focused_text(text: str, query: str, *, limit: int = 9, max_chars: int = 12_000) -> str:
    return DocumentView(text).prompt(query, limit=limit, max_chars=max_chars)
