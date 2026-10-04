import { marked } from 'marked';
import type { Token, Tokens } from 'marked';
import katex from 'katex';

/* =============================================================================
   Rich-text model for model answers.

   `marked` (GFM) tokenizes the answer; this module turns those tokens into a
   small, explicit tree that the React renderer maps to elements. The indirection
   is deliberate:

   - raw HTML never becomes an element — it is carried as inert text, so a
     `<script>` in an answer can only ever be displayed;
   - every URL passes `safeUrl` before it reaches an `href`;
   - math is lifted out before tokenizing, so `\[ … \]`, `\( … \)` and `$…$`
     survive CommonMark backslash escaping and code spans/blocks stay literal;
   - everything here is pure TypeScript, so `node --test` can cover it without a
     DOM, React or CSS.

   Run the tests with `npm test`.
   ========================================================================== */

/** Placeholder brackets that wrap a math index inside tokenized text. */
const MATH_OPEN = '\uE000';
const MATH_END = '\uE001';
const MATH_PLACEHOLDER = /\uE000(\d+)\uE001/g;

export type TableAlign = 'left' | 'center' | 'right' | null;

export type MathNode = { type: 'math'; tex: string; display: boolean };

export type InlineNode =
  | { type: 'text'; value: string }
  | { type: 'strong'; children: InlineNode[] }
  | { type: 'em'; children: InlineNode[] }
  | { type: 'del'; children: InlineNode[] }
  | { type: 'code'; value: string }
  | { type: 'link'; href: string; children: InlineNode[] }
  | { type: 'image'; alt: string; href: string | null }
  | { type: 'break' }
  | { type: 'sup'; children: InlineNode[] }
  | MathNode;

export type ListItem = { checked: boolean | null; children: BlockNode[] };

export type BlockNode =
  | { type: 'heading'; depth: number; children: InlineNode[] }
  | { type: 'paragraph'; children: InlineNode[] }
  | { type: 'list'; ordered: boolean; start: number; items: ListItem[] }
  | { type: 'blockquote'; children: BlockNode[] }
  | { type: 'code'; lang: string | null; value: string }
  | { type: 'table'; align: TableAlign[]; header: InlineNode[][]; rows: InlineNode[][][] }
  | { type: 'divider' }
  | MathNode;

/**
 * An inline construct lifted out of the prose before `marked` sees it, replaced
 * by a placeholder and restored after tokenizing. Lifting protects the source
 * from CommonMark escaping (`\[` would become `[`) and keeps code spans literal.
 */
type Lift = { kind: 'math'; tex: string; display: boolean } | { kind: 'sup'; value: string };

/* =============================================================================
   URL safety
   ========================================================================== */

/** Only these schemes may reach an `href`. Everything else is dropped. */
const SAFE_SCHEMES = new Set(['http:', 'https:', 'mailto:']);

/**
 * Returns the URL when it is safe to put in an `href`, otherwise `null`.
 *
 * `javascript:`, `data:`, `vbscript:`, protocol-relative and scheme-less values
 * are all rejected. Control characters are refused because they can hide a
 * scheme from a naive string check.
 */
export function safeUrl(raw: string | null | undefined): string | null {
  if (typeof raw !== 'string') return null;
  const value = raw.trim();
  if (!value) return null;
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(value)) return null;
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return null;
  }
  return SAFE_SCHEMES.has(parsed.protocol.toLowerCase()) ? value : null;
}

/* =============================================================================
   Math rendering
   ========================================================================== */

/**
 * Renders TeX to KaTeX markup, or `null` when the formula is not renderable
 * (invalid or still incomplete while streaming). Callers fall back to showing
 * the raw source as plain text, which keeps the response readable.
 *
 * `trust: false` disables `\href`, `\url`, `\htmlClass` and friends, so the
 * produced markup cannot carry a URL or a class chosen by the model.
 */
export function renderMathHtml(tex: string, display: boolean): string | null {
  const source = tex.trim();
  if (!source) return null;
  try {
    return katex.renderToString(source, {
      displayMode: display,
      throwOnError: true,
      trust: false,
      strict: false,
      maxExpand: 200,
      maxSize: 50,
      output: 'htmlAndMathml',
    });
  } catch {
    return null;
  }
}

/* =============================================================================
   Fenced code splitting
   ========================================================================== */

type Chunk = { type: 'text'; value: string } | { type: 'code'; lang: string | null; value: string };

const FENCE_OPEN = /^ {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*)/;
const FENCE_CLOSE = /^ {0,3}(`{3,}|~{3,})[ \t]*$/;

/**
 * Splits the source into prose and fenced code. Code never takes part in math
 * extraction or table parsing, and an unterminated fence (streaming) is still
 * emitted as code so nothing disappears.
 */
export function splitFencedCode(source: string): Chunk[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  const chunks: Chunk[] = [];
  let prose: string[] = [];
  let fence: string | null = null;
  let lang: string | null = null;
  let code: string[] = [];

  const flushProse = () => {
    if (prose.length) chunks.push({ type: 'text', value: prose.join('\n') });
    prose = [];
  };

  for (const line of lines) {
    if (fence === null) {
      const open = FENCE_OPEN.exec(line);
      if (open) {
        flushProse();
        fence = open[1];
        lang = open[2] ? open[2].trim() || null : null;
        code = [];
        continue;
      }
      prose.push(line);
      continue;
    }
    const close = FENCE_CLOSE.exec(line);
    if (close && close[1][0] === fence[0] && close[1].length >= fence.length) {
      chunks.push({ type: 'code', lang, value: code.join('\n') });
      fence = null;
      lang = null;
      code = [];
      continue;
    }
    code.push(line);
  }

  if (fence !== null) chunks.push({ type: 'code', lang, value: code.join('\n') });
  flushProse();
  return chunks;
}

/* =============================================================================
   Math extraction
   ========================================================================== */

/**
 * Lifts math out of prose and replaces each span with a placeholder.
 *
 * Inline code spans are copied verbatim first, so `` `$x$` `` stays code. An
 * unterminated delimiter is left alone, which is exactly the streaming fallback:
 * the fragment renders as ordinary text until the closing delimiter arrives.
 */
export function extractMath(source: string): { text: string; math: Lift[] } {
  const math: Lift[] = [];
  let out = '';
  let index = 0;

  const push = (tex: string, display: boolean) => {
    out += `${MATH_OPEN}${math.length}${MATH_END}`;
    math.push({ kind: 'math', tex: tex.trim(), display });
  };

  const pushSup = (value: string) => {
    out += `${MATH_OPEN}${math.length}${MATH_END}`;
    math.push({ kind: 'sup', value });
  };

  while (index < source.length) {
    if (source[index] === '`') {
      const ticks = /^`+/.exec(source.slice(index))?.[0] ?? '`';
      const close = source.indexOf(ticks, index + ticks.length);
      if (close >= 0) {
        out += source.slice(index, close + ticks.length);
        index = close + ticks.length;
        continue;
      }
      out += source.slice(index);
      break;
    }

    const rest = source.slice(index);
    const display = /^\$\$([\s\S]+?)\$\$/.exec(rest);
    if (display) {
      push(display[1], true);
      index += display[0].length;
      continue;
    }
    const bracket = /^\\\[([\s\S]+?)\\\]/.exec(rest);
    if (bracket) {
      push(bracket[1], true);
      index += bracket[0].length;
      continue;
    }
    const paren = /^\\\(([\s\S]+?)\\\)/.exec(rest);
    if (paren) {
      push(paren[1], false);
      index += paren[0].length;
      continue;
    }
    if (source[index] === '$') {
      const inline = matchInlineDollar(source, index);
      if (inline) {
        push(inline.tex, false);
        index = inline.end;
        continue;
      }
    }
    // `<sup>…</sup>` is the only raw HTML the answers legitimately carry
    // (citation markers). It becomes a real superscript element; every other
    // tag is left as inert text.
    if (source.startsWith('<sup>', index)) {
      const close = source.indexOf('</sup>', index + 5);
      if (close > index + 5) {
        pushSup(source.slice(index + 5, close).trim());
        index = close + 6;
        continue;
      }
    }

    out += source[index];
    index += 1;
  }

  return { text: out, math };
}

/**
 * Finds the closing `$` of inline math using the conservative Pandoc-style
 * rules: the opening `$` must not be followed by whitespace, the closing `$`
 * must hug its content, and a digit right after the closing `$` means this was
 * an amount of money (`$5 … $6`), not a formula.
 */
function matchInlineDollar(source: string, start: number): { tex: string; end: number } | null {
  const after = source[start + 1];
  if (after === undefined || /\s/.test(after)) return null;
  for (let index = start + 1; index < source.length; index += 1) {
    const char = source[index];
    if (char === '\n') return null;
    if (char !== '$') continue;
    const prev = source[index - 1];
    if (prev === '\\') continue;
    if (/\s/.test(prev)) return null;
    const next = source[index + 1];
    if (next !== undefined && /[0-9]/.test(next)) return null;
    const tex = source.slice(start + 1, index);
    if (!tex.trim()) return null;
    return { tex, end: index + 1 };
  }
  return null;
}

/* =============================================================================
   Token tree
   ========================================================================== */

/** Parses an answer into renderable blocks. Never throws on partial input. */
export function parseRichText(source: string): BlockNode[] {
  if (!source || !source.trim()) return [];
  const blocks: BlockNode[] = [];
  for (const chunk of splitFencedCode(source)) {
    if (chunk.type === 'code') {
      blocks.push({ type: 'code', lang: chunk.lang, value: chunk.value });
      continue;
    }
    const { text, math } = extractMath(chunk.value);
    if (!text.trim()) continue;
    let tokens: Token[];
    try {
      tokens = marked.lexer(text);
    } catch {
      blocks.push({ type: 'paragraph', children: [{ type: 'text', value: text }] });
      continue;
    }
    blocks.push(...blockNodes(tokens, math));
  }
  return blocks;
}

function blockNodes(tokens: Token[], math: Lift[]): BlockNode[] {
  const blocks: BlockNode[] = [];
  for (const token of tokens) blocks.push(...blockNode(token, math));
  return blocks;
}

function blockNode(token: Token, math: Lift[]): BlockNode[] {
  switch (token.type) {
    case 'space':
    case 'def':
      return [];
    case 'heading': {
      const heading = token as Tokens.Heading;
      const depth = Math.min(Math.max(heading.depth, 1), 6);
      return [{ type: 'heading', depth, children: inlineNodes(heading.tokens, math) }];
    }
    case 'paragraph': {
      const paragraph = token as Tokens.Paragraph;
      return paragraphBlock(inlineNodes(paragraph.tokens, math));
    }
    case 'text': {
      const text = token as Tokens.Text;
      const children = text.tokens?.length ? inlineNodes(text.tokens, math) : splitPlaceholders(text.text, math);
      return paragraphBlock(children);
    }
    case 'code': {
      const code = token as Tokens.Code;
      const lang = code.lang ? code.lang.trim().split(/\s+/)[0] || null : null;
      return [{ type: 'code', lang, value: code.text }];
    }
    case 'blockquote': {
      const quote = token as Tokens.Blockquote;
      return [{ type: 'blockquote', children: blockNodes(quote.tokens, math) }];
    }
    case 'list': {
      const list = token as Tokens.List;
      return [
        {
          type: 'list',
          ordered: Boolean(list.ordered),
          start: typeof list.start === 'number' && list.start > 0 ? list.start : 1,
          items: list.items.map((item) => ({
            checked: item.task ? Boolean(item.checked) : null,
            children: blockNodes(item.tokens, math),
          })),
        },
      ];
    }
    case 'table': {
      const table = token as Tokens.Table;
      return [
        {
          type: 'table',
          align: table.align.map((align) => align ?? null),
          header: table.header.map((cell) => inlineNodes(cell.tokens, math)),
          rows: table.rows.map((row) => row.map((cell) => inlineNodes(cell.tokens, math))),
        },
      ];
    }
    case 'hr':
      return [{ type: 'divider' }];
    case 'html': {
      // Raw HTML is inert text: React escapes it, no element is created.
      const html = token as Tokens.HTML;
      return html.text.trim() ? [{ type: 'paragraph', children: [{ type: 'text', value: html.text }] }] : [];
    }
    default: {
      const generic = token as Tokens.Generic;
      if (generic.tokens?.length) return blockNodes(generic.tokens, math);
      const value = typeof generic.raw === 'string' ? generic.raw : '';
      return value.trim() ? [{ type: 'paragraph', children: [{ type: 'text', value }] }] : [];
    }
  }
}

/** A paragraph holding a single display formula becomes a block formula. */
function paragraphBlock(children: InlineNode[]): BlockNode[] {
  if (children.length === 1 && children[0].type === 'math' && children[0].display) {
    return [{ type: 'math', tex: children[0].tex, display: true }];
  }
  if (!children.length) return [];
  return [{ type: 'paragraph', children }];
}

function inlineNodes(tokens: Token[] | undefined, math: Lift[]): InlineNode[] {
  const nodes: InlineNode[] = [];
  for (const token of tokens ?? []) nodes.push(...inlineNode(token, math));
  return nodes;
}

function inlineNode(token: Token, math: Lift[]): InlineNode[] {
  switch (token.type) {
    case 'text': {
      const text = token as Tokens.Text;
      // A container text token keeps its inline children; a leaf one is literal.
      if (text.tokens?.length) return inlineNodes(text.tokens, math);
      return splitPlaceholders(text.text, math);
    }
    case 'escape':
      return [{ type: 'text', value: (token as Tokens.Escape).text }];
    case 'strong':
      return [{ type: 'strong', children: inlineNodes((token as Tokens.Strong).tokens, math) }];
    case 'em':
      return [{ type: 'em', children: inlineNodes((token as Tokens.Em).tokens, math) }];
    case 'del':
      return [{ type: 'del', children: inlineNodes((token as Tokens.Del).tokens, math) }];
    case 'codespan':
      return [{ type: 'code', value: (token as Tokens.Codespan).text }];
    case 'br':
      return [{ type: 'break' }];
    case 'checkbox':
      // Task state is carried by the list item itself.
      return [];
    case 'link': {
      const link = token as Tokens.Link;
      const children = inlineNodes(link.tokens, math);
      const href = safeUrl(link.href);
      if (!href) return children.length ? children : [{ type: 'text', value: link.text }];
      return [{ type: 'link', href, children }];
    }
    case 'image': {
      const image = token as Tokens.Image;
      return [{ type: 'image', alt: image.text || '', href: safeUrl(image.href) }];
    }
    case 'html':
      return [{ type: 'text', value: (token as Tokens.HTML).text }];
    default: {
      const generic = token as Tokens.Generic;
      if (generic.tokens?.length) return inlineNodes(generic.tokens, math);
      const value = typeof generic.text === 'string' ? generic.text : generic.raw;
      return typeof value === 'string' && value ? [{ type: 'text', value }] : [];
    }
  }
}

/** Expands lifted placeholders back into math and superscript nodes. */
function splitPlaceholders(value: string, math: Lift[]): InlineNode[] {
  const nodes: InlineNode[] = [];
  let last = 0;
  MATH_PLACEHOLDER.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = MATH_PLACEHOLDER.exec(value)) !== null) {
    if (match.index > last) nodes.push({ type: 'text', value: value.slice(last, match.index) });
    const item = math[Number(match[1])];
    if (item?.kind === 'math') nodes.push({ type: 'math', tex: item.tex, display: item.display });
    if (item?.kind === 'sup') nodes.push({ type: 'sup', children: [{ type: 'text', value: item.value }] });
    last = match.index + match[0].length;
  }
  if (last < value.length) nodes.push({ type: 'text', value: value.slice(last) });
  return nodes;
}
