import type { MessageWebSource } from '@/types';

/* =============================================================================
   Web-source presentation helpers.

   These are pure, UI-free functions so the API mapper and the sources panel can
   share one definition of "domain" and how the legacy
   Markdown block is recognised.
   ========================================================================== */

/**
 * The exact bold headings the backend used to append. New answers never carry
 * this block; the list exists only so historical messages can be cleaned up.
 *
 * This is an explicit allow-list rather than a pattern over any line mentioning
 * "источник": an answer may legitimately contain `**Источник**`,
 * `Источник: учебник` or a question about sources, and none of those may be cut.
 */
const LEGACY_HEADINGS = [
  /^\*\*\s*Использованные\s+источники\s*\*\*$/i,
  /^\*\*\s*Источники\s+поиска\s*\*\*$/i,
  /^\*\*\s*Источники\s*\*\*$/i,
];

function isLegacyHeading(line: string): boolean {
  return LEGACY_HEADINGS.some((pattern) => pattern.test(line));
}

/** A single `- [Title](https://…)` bullet inside the legacy block. */
const LEGACY_LINK = /^[-*+]\s*\[([^\]]*)\]\(\s*(\S+?)\s*\)$/;

/** Hostname without a leading `www.`, or `''` when the URL cannot be parsed. */
export function domainFromUrl(url: string): string {
  try {
    return new URL(url.trim()).hostname.replace(/^www\./i, '');
  } catch {
    return '';
  }
}

/**
 * Deduplicate by URL. The first entry wins so backend-provided metadata is
 * preferred over a fallback parsed from the answer text.
 */
export function dedupeWebSources(sources: MessageWebSource[]): MessageWebSource[] {
  const seen = new Set<string>();
  const unique: MessageWebSource[] = [];
  for (const source of sources) {
    const key = source.url.trim();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    unique.push(source);
  }
  return unique;
}

/**
 * Remove a trailing legacy "**Использованные источники**" Markdown block from
 * an answer and return its links as structured sources.
 *
 * The block is only recognised when it sits at the very end of the content and
 * every following non-empty line is a Markdown link bullet. Anything else is
 * left byte-for-byte untouched, so ordinary answers are never reformatted.
 */
export function extractLegacySources(content: string): {
  content: string;
  sources: MessageWebSource[];
} {
  const unchanged = { content, sources: [] as MessageWebSource[] };
  if (!content) return unchanged;

  const lines = content.split('\n');
  const body = (line: string) => line.replace(/\r$/, '').trim();

  // Walk up from the end and locate the heading. Any non-link, non-heading
  // line before reaching it proves this is not the appended block.
  let headingIndex = -1;
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = body(lines[index]);
    if (!line) continue;
    if (isLegacyHeading(line)) {
      headingIndex = index;
      break;
    }
    if (!LEGACY_LINK.test(line)) return unchanged;
  }
  if (headingIndex < 0) return unchanged;

  const sources = dedupeWebSources(
    lines.slice(headingIndex + 1).flatMap((rawLine, offset): MessageWebSource[] => {
      const match = LEGACY_LINK.exec(body(rawLine));
      if (!match) return [];
      const url = match[2];
      const title = match[1].trim();
      return [
        {
          id: `legacy-web-${headingIndex + 1 + offset}`,
          title: title || domainFromUrl(url) || url,
          url,
        },
      ];
    }),
  );

  // Drop the heading and the blank line(s) that separated it from the answer.
  let cut = headingIndex;
  while (cut > 0 && body(lines[cut - 1]) === '') cut -= 1;

  const kept = lines.slice(0, cut).join('\n');
  // The removed separator also carried the answer line's CRLF terminator.
  return { content: kept.endsWith('\r') ? kept.slice(0, -1) : kept, sources };
}
