import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { createStreamingRichTextParser, answerBlockKind } from './streamingRichText.ts';

test('token append preserves finished paragraph and KaTeX node identities', () => {
  const parse = createStreamingRichTextParser();
  const a = parse('Введение.\n\n\\[x=2a\\]\n\nОтвет');
  const b = parse('Введение.\n\n\\[x=2a\\]\n\nОтвет: 5.');
  assert.equal(a[0], b[0]); assert.equal(a[1], b[1]); assert.notEqual(a[2], b[2]);
  assert.equal(answerBlockKind(b[2]), 'ответ');
});
test('rewritten response replaces nodes and inline math stays inline', () => {
  const parse = createStreamingRichTextParser();
  const a = parse('Важно: \\(x=2a\\).');
  assert.equal(answerBlockKind(a[0]), 'важно');
  assert.equal(a[0].type, 'paragraph');
  const b = parse('Обычный текст'); assert.notEqual(a[0], b[0]);
  assert.equal(answerBlockKind(b[0]), undefined);
});

import { parseRichText } from './richText.ts';
test('completed prose is not parsed again on later tokens', () => {
  const calls: string[] = [];
  const parse = createStreamingRichTextParser((source) => { calls.push(source); return parseRichText(source); });
  parse('Начало.\n\nСледующий'); calls.length = 0;
  parse('Начало.\n\nСледующий абзац.');
  assert.deepEqual(calls, ['Следующий абзац.']);
});
test('all token prefixes match full parsing including multiline math, lists, code and reference links', () => {
  const samples = [
    'Введение.\n\n\\[x=\\frac{a^2+b^2}{2ab}\\]\n\nОтвет: 5.',
    'Сначала\n\n$$a\n\n+b$$\n\nОтвет: 5.',
    'Введение.\n\n1. Первый\n\n   продолжение\n2. Второй\n\nОтвет.',
    'Текст [ссылка][ref].\n\n[ref]: https://example.com\n\nГотово.',
    'Начало.\n\n```ts\na\n\nb\n```\n\nКонец.',
    'Начало.\n\n| A | B |\n|---|---|\n| 1 | 2 |',
  ];
  for (const source of samples) {
    const parse = createStreamingRichTextParser();
    for (let end = 1; end <= source.length; end++) {
      const text = source.slice(0, end);
      assert.deepEqual(parse(text), parseRichText(text), `${end}: ${text}`);
    }
  }
});
