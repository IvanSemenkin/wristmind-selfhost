import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import {
  parseRichText,
  renderMathHtml,
  safeUrl,
  splitFencedCode,
  type BlockNode,
  type InlineNode,
} from './richText.ts';
import { extractLegacySources } from './webSources.ts';

/* Run with:  npm test   (node --test --experimental-strip-types src/lib/) */

/* ---------- helpers ------------------------------------------------------ */

function blockOfType<T extends BlockNode['type']>(
  source: string,
  type: T,
): Extract<BlockNode, { type: T }> {
  const found = parseRichText(source).find((block) => block.type === type);
  assert.ok(found, `expected a "${type}" block in ${JSON.stringify(source)}`);
  return found as Extract<BlockNode, { type: T }>;
}

function paragraphInline(source: string): InlineNode[] {
  return blockOfType(source, 'paragraph').children;
}

/** Every `type` anywhere in the parsed tree. */
function collectTypes(value: unknown, out: string[] = []): string[] {
  if (Array.isArray(value)) {
    for (const item of value) collectTypes(item, out);
    return out;
  }
  if (value && typeof value === 'object') {
    const node = value as { type?: unknown };
    if (typeof node.type === 'string') out.push(node.type);
    for (const child of Object.values(value as Record<string, unknown>)) collectTypes(child, out);
  }
  return out;
}

function typesOf(source: string): Set<string> {
  return new Set(collectTypes(parseRichText(source)));
}

/* ---------- inline formatting ------------------------------------------- */

test('1. bold becomes a strong node', () => {
  assert.deepEqual(parseRichText('**жирный**'), [
    { type: 'paragraph', children: [{ type: 'strong', children: [{ type: 'text', value: 'жирный' }] }] },
  ]);
});

test('2. italic becomes an em node', () => {
  assert.deepEqual(paragraphInline('*курсив*'), [
    { type: 'em', children: [{ type: 'text', value: 'курсив' }] },
  ]);
});

test('3. strikethrough becomes a del node', () => {
  assert.deepEqual(paragraphInline('~~старое~~'), [
    { type: 'del', children: [{ type: 'text', value: 'старое' }] },
  ]);
});

test('4. inline code keeps its literal text', () => {
  assert.deepEqual(paragraphInline('до `a < b` после'), [
    { type: 'text', value: 'до ' },
    { type: 'code', value: 'a < b' },
    { type: 'text', value: ' после' },
  ]);
});

/* ---------- headings ----------------------------------------------------- */

test('5. H1-H4 map to heading depths', () => {
  const depths = parseRichText('# H1\n\n## H2\n\n### H3\n\n#### H4').map((block) =>
    block.type === 'heading' ? block.depth : -1,
  );
  assert.deepEqual(depths, [1, 2, 3, 4]);
  const heading = blockOfType('## Заголовок', 'heading');
  assert.deepEqual(heading.children, [{ type: 'text', value: 'Заголовок' }]);
});

/* ---------- lists -------------------------------------------------------- */

test('6. unordered list keeps bullet items', () => {
  const list = blockOfType('- один\n- два', 'list');
  assert.equal(list.ordered, false);
  assert.equal(list.items.length, 2);
  assert.deepEqual(list.items[0].children, [
    { type: 'paragraph', children: [{ type: 'text', value: 'один' }] },
  ]);
});

test('7. ordered list keeps numbering', () => {
  const list = blockOfType('1. один\n2. два', 'list');
  assert.equal(list.ordered, true);
  assert.equal(list.start, 1);
  assert.equal(list.items.length, 2);
});

test('8. a nested list is preserved two levels deep', () => {
  const list = blockOfType('- один\n    - вложенный', 'list');
  const nested = list.items[0].children.find((child) => child.type === 'list');
  assert.ok(nested, 'expected a nested list inside the first item');
  assert.equal(nested.type === 'list' ? nested.items.length : 0, 1);
});

test('16. task list items are read-only checkboxes', () => {
  const list = blockOfType('- [ ] задача\n- [x] готово', 'list');
  assert.deepEqual(
    list.items.map((item) => item.checked),
    [false, true],
  );
  // The raw GFM checkbox token must not leak into the tree.
  assert.equal(typesOf('- [ ] задача').has('checkbox'), false);
});

/* ---------- block structure --------------------------------------------- */

test('9. a quote becomes a blockquote', () => {
  const quote = blockOfType('> цитата', 'blockquote');
  assert.deepEqual(quote.children, [
    { type: 'paragraph', children: [{ type: 'text', value: 'цитата' }] },
  ]);
});

test('10. a fenced code block keeps its language and body', () => {
  const code = blockOfType('```js\nconst a = 1;\n```', 'code');
  assert.equal(code.lang, 'js');
  assert.equal(code.value, 'const a = 1;');
});

test('11. an unclosed fenced code block still renders as code', () => {
  const code = blockOfType('```js\nconst a = 1;', 'code');
  assert.equal(code.lang, 'js');
  assert.equal(code.value, 'const a = 1;');
  assert.equal(parseRichText('```js\nconst a = 1;').length, 1);
});

test('17. a thematic break becomes a divider', () => {
  assert.equal(typesOf('текст\n\n---\n\nещё').has('divider'), true);
  assert.equal(typesOf('текст\n\n***\n\nещё').has('divider'), true);
  assert.equal(typesOf('текст\n\n___\n\nещё').has('divider'), true);
});

test('paragraphs stay separate and are never merged into one line', () => {
  const blocks = parseRichText('Первый абзац.\n\nВторой абзац.');
  assert.equal(blocks.length, 2);
  assert.equal(blocks.every((block) => block.type === 'paragraph'), true);
});

/* ---------- tables ------------------------------------------------------- */

test('12. a Markdown table becomes a table block', () => {
  const table = blockOfType('| Колонка | Другая |\n|:--|--:|\n| 1 | 2 |', 'table');
  assert.deepEqual(table.align, ['left', 'right']);
  assert.equal(table.header.length, 2);
  assert.deepEqual(table.header[0], [{ type: 'text', value: 'Колонка' }]);
  assert.equal(table.rows.length, 1);
  assert.deepEqual(table.rows[0][1], [{ type: 'text', value: '2' }]);
  // The separator row never survives into the model.
  assert.equal(collectTypes(table).filter((type) => type === 'text').length, 4);
});

test('13. a table inside a fenced code block stays code', () => {
  const blocks = parseRichText('```\n| a | b |\n|---|---|\n| 1 | 2 |\n```');
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].type, 'code');
  assert.equal(blocks[0].type === 'code' ? blocks[0].value : '', '| a | b |\n|---|---|\n| 1 | 2 |');
  assert.equal(typesOf('```\n| a | b |\n```').has('table'), false);
});

/* ---------- links and images -------------------------------------------- */

test('14. a Markdown link keeps its label and safe href', () => {
  assert.deepEqual(paragraphInline('[документ](https://example.org/doc)'), [
    { type: 'link', href: 'https://example.org/doc', children: [{ type: 'text', value: 'документ' }] },
  ]);
  // Unsafe destinations degrade to plain label text.
  assert.deepEqual(paragraphInline('[клик](javascript:alert(1))'), [{ type: 'text', value: 'клик' }]);
  assert.deepEqual(paragraphInline('[клик](data:text/html;base64,PHNjcmlwdD4=)'), [
    { type: 'text', value: 'клик' },
  ]);
});

test('15. an image becomes a labelled element, never a raw tag', () => {
  assert.deepEqual(paragraphInline('![схема](https://example.org/a.png)'), [
    { type: 'image', alt: 'схема', href: 'https://example.org/a.png' },
  ]);
  // An unsafe image destination can never reach an href.
  const unsafe = paragraphInline('![схема](javascript:alert(1))');
  assert.equal(unsafe.some((node) => node.type === 'image' && node.href !== null), false);
  assert.equal(unsafe.some((node) => node.type === 'link'), false);
});

/* ---------- math --------------------------------------------------------- */

test('18. inline $x^2$ becomes a math node', () => {
  assert.deepEqual(paragraphInline('$x^2$'), [{ type: 'math', tex: 'x^2', display: false }]);
  assert.match(renderMathHtml('x^2', false) ?? '', /katex/);
});

test('19. \\[ … \\] becomes display math and renders', () => {
  const math = blockOfType('\\[x=9 \\text{ или } x=-9\\]', 'math');
  assert.equal(math.display, true);
  assert.match(math.tex, /\\text/);
  assert.match(renderMathHtml(math.tex, true) ?? '', /katex/);
});

test('20. \\frac{a}{b} renders both inline and display', () => {
  assert.deepEqual(paragraphInline('$\\frac{a}{b}$'), [
    { type: 'math', tex: '\\frac{a}{b}', display: false },
  ]);
  assert.match(renderMathHtml('\\frac{a}{b}', false) ?? '', /katex/);
});

test('21. \\sqrt{x} renders', () => {
  assert.match(renderMathHtml('\\sqrt{x}', false) ?? '', /katex/);
  assert.deepEqual(paragraphInline('$\\sqrt{x}$'), [{ type: 'math', tex: '\\sqrt{x}', display: false }]);
});

test('22. an unfinished formula stays plain text instead of breaking the answer', () => {
  const inline = typesOf('Корень $x + 1');
  assert.equal(inline.has('math'), false);

  const display = typesOf('Формула:\n\n$$\\frac{');
  assert.equal(display.has('math'), false);

  const paragraph = paragraphInline('Корень $x + 1');
  const text = paragraph.map((node) => (node.type === 'text' ? node.value : '')).join('');
  assert.equal(text.includes('$x + 1'), true);
});

test('22b. partial inline markup during streaming never throws or empties the answer', () => {
  for (const partial of ['**текст', '*курсив', '`код', '[ссылка](htt', '$$\\frac{', '> цитата без конца']) {
    const blocks = parseRichText(partial);
    assert.ok(blocks.length > 0, `expected readable output for ${JSON.stringify(partial)}`);
  }
  assert.equal(typesOf('**текст').has('strong'), false);
  assert.equal(typesOf('`код').has('code'), false);
  assert.equal(typesOf('[ссылка](htt').has('link'), false);
});

test('math inside inline code is left alone', () => {
  assert.deepEqual(paragraphInline('пример `$x$`'), [
    { type: 'text', value: 'пример ' },
    { type: 'code', value: '$x$' },
  ]);
});

/* ---------- legacy source block ----------------------------------------- */

test('23. the legacy source block is hidden and its links recovered', () => {
  const legacy = extractLegacySources(
    'Ответ.\n\n**Использованные источники**\n- [A](https://a.example)\n- [B](https://b.example)',
  );
  assert.equal(legacy.content, 'Ответ.');
  assert.deepEqual(
    legacy.sources.map((source) => source.url),
    ['https://a.example', 'https://b.example'],
  );

  for (const heading of ['**Источники поиска**', '**Источники**', '**ИСПОЛЬЗОВАННЫЕ ИСТОЧНИКИ**']) {
    const cleaned = extractLegacySources(`Тело.\n\n${heading}\n- [A](https://a.example)`);
    assert.equal(cleaned.content, 'Тело.');
    assert.equal(cleaned.sources.length, 1);
  }

  // Whatever the call site, the renderer never shows the heading itself.
  const rendered = JSON.stringify(parseRichText(legacy.content));
  assert.equal(rendered.includes('Использованные источники'), false);
});

test('24. ordinary mentions of a source are never removed', () => {
  for (const text of [
    'Источник: учебник, с. 42',
    '**Источник**\n\nОсновной ответ: 5.',
    'Какие источники использовал автор?',
    'Основной источник информации — архив.',
  ]) {
    assert.equal(extractLegacySources(text).content, text);
    assert.equal(extractLegacySources(text).sources.length, 0);
  }
});

/* ---------- safety ------------------------------------------------------- */

test('25. malicious HTML is inert text, never an element', () => {
  const types = typesOf('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>');
  assert.equal(types.has('html'), false);
  assert.equal(types.has('link'), false);
  assert.equal(types.has('image'), false);

  // The markup survives as readable text (escaped by React at render time).
  const json = JSON.stringify(parseRichText('<script>alert(1)</script>'));
  assert.equal(json.includes('<script>'), true);

  assert.equal(safeUrl('javascript:alert(1)'), null);
  assert.equal(safeUrl('JaVaScRiPt:alert(1)'), null);
  assert.equal(safeUrl('data:text/html;base64,PHNjcmlwdD4='), null);
  assert.equal(safeUrl('vbscript:msgbox(1)'), null);
  assert.equal(safeUrl('//evil.example/x'), null);
  assert.equal(safeUrl('\u0000javascript:alert(1)'), null);
  assert.equal(safeUrl('https://example.org/ok'), 'https://example.org/ok');
  assert.equal(safeUrl('mailto:a@example.org'), 'mailto:a@example.org');
});

test('25b. KaTeX output never carries a model-chosen link', () => {
  // With `trust: false` KaTeX refuses `\href`: it renders the command name in
  // red and only echoes the source inside the (inert, escaped) MathML
  // annotation — no anchor and no href attribute is produced.
  const html = renderMathHtml('\\href{javascript:alert(1)}{x}', false);
  assert.ok(html, 'expected KaTeX to render an error placeholder rather than throw');
  assert.equal(/<a[\s>]/i.test(html), false);
  assert.equal(/href\s*=\s*["']?javascript:/i.test(html), false);
});

/* ---------- robustness --------------------------------------------------- */

test('26. a very long URL or word does not break the tree', () => {
  const longUrl = `https://example.org/${'a'.repeat(400)}`;
  const link = paragraphInline(`[ссылка](${longUrl})`);
  assert.deepEqual(link, [{ type: 'link', href: longUrl, children: [{ type: 'text', value: 'ссылка' }] }]);

  const word = 'я'.repeat(400);
  assert.deepEqual(paragraphInline(word), [{ type: 'text', value: word }]);
});

test('an empty or whitespace answer renders nothing', () => {
  assert.deepEqual(parseRichText(''), []);
  assert.deepEqual(parseRichText('   \n\n  '), []);
});

test('fenced code splitting keeps prose order around code', () => {
  const chunks = splitFencedCode('до\n\n```\nкод\n```\n\nпосле');
  assert.deepEqual(chunks, [
    { type: 'text', value: 'до\n' },
    { type: 'code', lang: null, value: 'код' },
    { type: 'text', value: '\nпосле' },
  ]);
});

test('citation markers stay superscripts, other HTML does not', () => {
  assert.deepEqual(paragraphInline('факт<sup>1</sup>'), [
    { type: 'text', value: 'факт' },
    { type: 'sup', children: [{ type: 'text', value: '1' }] },
  ]);
  assert.equal(typesOf('факт<sup>1</sup>').has('html'), false);
});
