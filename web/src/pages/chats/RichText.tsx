import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import 'katex/dist/katex.min.css';

import {
  parseRichText,
  renderMathHtml,
  type BlockNode,
  type InlineNode,
  type TableAlign,
} from '@/lib/richText';
import { extractLegacySources } from '@/lib/webSources';

import styles from './RichText.module.css';

/* =============================================================================
   Assistant answer renderer.

   `parseRichText` turns the answer into an explicit node tree; this file maps
   that tree to React elements. Nothing here ever injects model-authored markup:

   - text nodes render as React children, so `<script>` in an answer is escaped
     and displayed, never executed;
   - anchors are created only from a `safeUrl` result, always with
     `target="_blank"` and `rel="noopener noreferrer"`;
   - the single `dangerouslySetInnerHTML` is fed by KaTeX itself (rendered with
     `trust: false`), which is the sanctioned way to display KaTeX output.

   The legacy Markdown source block is stripped again here, so no call site can
   accidentally render it as prose.
   ========================================================================== */

const HEADING_STYLE = [styles.heading1, styles.heading2, styles.heading3, styles.heading4];

export function RichText({ content, className }: { content: string; className?: string }) {
  const blocks = useMemo(() => parseRichText(extractLegacySources(content ?? '').content), [content]);

  if (!blocks.length) return null;
  return (
    <div className={className}>
      {blocks.map((block, index) => (
        <Block key={index} node={block} />
      ))}
    </div>
  );
}

function Block({ node }: { node: BlockNode }) {
  switch (node.type) {
    case 'heading': {
      const level = Math.min(node.depth, 4);
      const Tag = (['h1', 'h2', 'h3', 'h4'] as const)[level - 1];
      return <Tag className={HEADING_STYLE[level - 1]}>{inline(node.children)}</Tag>;
    }
    case 'paragraph':
      return <div className={styles.paragraph}>{inline(node.children)}</div>;
    case 'list':
      return <ListNode node={node} />;
    case 'blockquote':
      return (
        <blockquote className={styles.blockquote}>
          {node.children.map((child, index) => (
            <Block key={index} node={child} />
          ))}
        </blockquote>
      );
    case 'code':
      return <CodeBlock lang={node.lang} value={node.value} />;
    case 'table':
      return <TableView node={node} />;
    case 'divider':
      return <hr className={styles.divider} />;
    case 'math':
      return <MathView tex={node.tex} display />;
  }
}

function ListNode({ node }: { node: Extract<BlockNode, { type: 'list' }> }) {
  const items = node.items.map((item, index) => (
    <li key={index} className={item.checked === null ? styles.listItem : styles.taskItem}>
      {item.checked !== null && (
        <span
          className={styles.taskBox}
          data-checked={item.checked ? 'true' : 'false'}
          role="img"
          aria-label={item.checked ? 'Выполнено' : 'Не выполнено'}
        >
          {item.checked ? '✓' : ''}
        </span>
      )}
      <div className={styles.listItemBody}>
        {item.children.map((child, childIndex) => (
          <Block key={childIndex} node={child} />
        ))}
      </div>
    </li>
  ));

  return node.ordered ? (
    <ol className={styles.list} start={node.start}>
      {items}
    </ol>
  ) : (
    <ul className={styles.list}>{items}</ul>
  );
}

function CodeBlock({ lang, value }: { lang: string | null; value: string }) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    const clipboard = navigator.clipboard;
    if (!clipboard) return;
    void clipboard.writeText(value).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1400);
      },
      () => undefined,
    );
  };

  return (
    <div className={styles.codeBlock}>
      <div className={styles.codeHeader}>
        <span className={styles.codeLang}>{lang ?? 'код'}</span>
        <button type="button" className={styles.copyButton} onClick={copy}>
          {copied ? 'Скопировано' : 'Копировать'}
        </button>
      </div>
      {/* Code is text: React escapes it, so HTML/JS inside is never executed. */}
      <pre className={styles.codePre}>
        <code>{value}</code>
      </pre>
    </div>
  );
}

function TableView({ node }: { node: Extract<BlockNode, { type: 'table' }> }) {
  return (
    // Horizontal overflow is contained here; the message layout never widens.
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            {node.header.map((cell, index) => (
              <th key={index} data-align={alignOf(node.align, index)}>
                {inline(cell)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {node.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} data-align={alignOf(node.align, cellIndex)}>
                  {inline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function alignOf(align: TableAlign[], index: number): string | undefined {
  return align[index] ?? undefined;
}

/**
 * KaTeX output, or the raw fragment while a formula is invalid/incomplete (for
 * example mid-stream). The fallback is plain text, so a half-arrived `\frac{`
 * never hides the already received part of the answer.
 */
function MathView({ tex, display }: { tex: string; display: boolean }) {
  const html = useMemo(() => renderMathHtml(tex, display), [tex, display]);
  if (!html) {
    return <code className={styles.mathFallback}>{display ? `$$${tex}$$` : `$${tex}$`}</code>;
  }
  return (
    <span
      className={display ? styles.mathBlock : styles.mathInline}
      // Only KaTeX-generated markup reaches this branch (trust: false).
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function inline(nodes: InlineNode[]): ReactNode[] {
  return nodes.map((node, index) => <Inline key={index} node={node} />);
}

function Inline({ node }: { node: InlineNode }) {
  switch (node.type) {
    case 'text':
      return <>{node.value}</>;
    case 'strong':
      return <strong className={styles.strong}>{inline(node.children)}</strong>;
    case 'em':
      return <em>{inline(node.children)}</em>;
    case 'del':
      return <del>{inline(node.children)}</del>;
    case 'code':
      return <code className={styles.inlineCode}>{node.value}</code>;
    case 'break':
      return <br />;
    case 'link':
      return (
        <a
          className={styles.link}
          href={node.href}
          target="_blank" rel="noopener noreferrer"
        >
          {inline(node.children)}
        </a>
      );
    case 'image': {
      const label = node.alt ? `Изображение: ${node.alt}` : 'Изображение';
      return node.href ? (
        <a className={styles.image} href={node.href} target="_blank" rel="noopener noreferrer">
          {label}
        </a>
      ) : (
        <span className={styles.image}>{label}</span>
      );
    }
    case 'math':
      return <MathView tex={node.tex} display={node.display} />;
    case 'sup':
      return <sup className={styles.citation}>{inline(node.children)}</sup>;
  }
}
