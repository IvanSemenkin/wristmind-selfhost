import { parseRichText, type BlockNode } from './richText.ts';

// These constructs can bind paragraphs across boundaries or resolve earlier links.
// Keep the exact full parser for them; ordinary prose/math can seal completed paragraphs.
function needsWholeDocument(source: string) {
  return /^(?: {0,3}(?:`{3,}|~{3,}|>|[-+*]\s|\d+[.)]\s)| {4}\S)|\||(?<!\\)\[|`|<|\r/m.test(source);
}

function balancedMath(source: string) {
  let close = '';
  for (let i = 0; i < source.length; i++) {
    if (close && source.startsWith(close, i)) { i += close.length - 1; close = ''; continue; }
    if (source[i] === '\\') {
      if (!close && (source[i + 1] === '(' || source[i + 1] === '[')) {
        close = source[i + 1] === '(' ? '\\)' : '\\]';
      }
      i++; continue;
    }
    if (!close && source[i] === '$') {
      close = source[i + 1] === '$' ? '$$' : '$';
      if (close === '$$') i++;
    }
  }
  return !close;
}

/** Seal independent paragraphs; retain exact Markdown fallback and stable React nodes. */
export function createStreamingRichTextParser(parse = parseRichText) {
  let previous: { signature: string; node: BlockNode }[] = [];
  let previousSource = '';
  let sealedSource = '';
  let sealed: BlockNode[] = [];
  return (source: string) => {
    if (source === previousSource) return previous.map((entry) => entry.node);
    let parsed: BlockNode[];
    if (needsWholeDocument(source)) {
      sealedSource = ''; sealed = [];
      parsed = parse(source);
    } else {
      if (!source.startsWith(sealedSource)) { sealedSource = ''; sealed = []; }
      const tail = source.slice(sealedSource.length);
      let boundary = 0;
      for (const match of tail.matchAll(/\n[ \t]*\n/g)) {
        const end = match.index! + match[0].length;
        if (balancedMath(tail.slice(0, end))) boundary = end;
      }
      if (boundary) {
        const finished = tail.slice(0, boundary);
        sealed.push(...parse(finished)); sealedSource += finished;
      }
      parsed = [...sealed, ...parse(tail.slice(boundary))];
    }
    const next = parsed.map((node, index) => {
      if (previous[index]?.node === node) return previous[index];
      const signature = JSON.stringify(node);
      return previous[index]?.signature === signature ? previous[index] : { signature, node: retainChildren(node, previous[index]?.node) };
    });
    previous = next; previousSource = source;
    return next.map((entry) => entry.node);
  };
}

/** Keep completed descendants stable while the last paragraph of a card grows. */
function retainChildren(node: BlockNode, previous?: BlockNode): BlockNode {
  if (!previous || previous.type !== node.type) return node;
  if (JSON.stringify(node) === JSON.stringify(previous)) return previous;
  if ((node.type === 'callout' || node.type === 'blockquote')
    && (previous.type === 'callout' || previous.type === 'blockquote')) {
    return { ...node, children: node.children.map((child, i) => retainChildren(child, previous.children[i])) };
  }
  if (node.type === 'list' && previous.type === 'list') {
    return { ...node, items: node.items.map((item, i) => ({ ...item,
      children: item.children.map((child, j) => retainChildren(child, previous.items[i]?.children[j])) })) };
  }
  return node;
}

export function answerBlockKind(node: BlockNode): string | undefined {
  if (node.type !== 'paragraph' && node.type !== 'heading') return;
  const first = node.children[0];
  const text = first?.type === 'text' ? first.value : first?.type === 'strong'
    ? first.children.map((part) => part.type === 'text' ? part.value : '').join('') : '';
  const label = /^(Важно|Ответ|Ошибка|Подсказка|Решение)(?:\s*:|$)/i.exec(text.trim());
  return label?.[1].toLowerCase();
}
