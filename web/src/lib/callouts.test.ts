import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { parseRichText, renderMathHtml, type BlockNode } from './richText.ts';
import { createStreamingRichTextParser } from './streamingRichText.ts';

const callouts = (source: string) => parseRichText(source).filter((n): n is Extract<BlockNode, {type:'callout'}> => n.type === 'callout');
const types = (value: unknown): string[] => Array.isArray(value) ? value.flatMap(types)
  : value && typeof value === 'object' ? [...('type' in value ? [String(value.type)] : []), ...Object.values(value).flatMap(types)] : [];

test('six explicit callout types, optional Markdown titles and adjacent cards', () => {
  const source = ['Важно','Подсказка','Ошибка','Пример','Ответ','Информация'].map(label => `> [${label}]\n> Текст.`).join('\n\n');
  assert.deepEqual(callouts(source).map(n=>n.kind), ['important','tip','error','example','answer','info']);
  assert.ok(callouts(source).every(n=>n.title.length===0 && n.children.length===1));
  const titled=callouts('> [Важно] **ОДЗ** для \\(x\\)\n> Знаменатель не равен нулю.')[0];
  assert.ok(types(titled.title).includes('strong'));
  assert.ok(types(titled.title).includes('math'));
  assert.equal(titled.children.length,1);
});

test('callout reuses Markdown: nested lists, references, table, code, chart and KaTeX', () => {
  const source = '> [Пример] Решение\n>\n> 1. **Первый** шаг: \\(x=2\\).\n>    - [Источник][ref]\n>\n> \\[x=\\frac{a^2+b^2}{2ab}\\]\n>\n> | A | B |\n> |---|---|\n> | 1 | 2 |\n>\n> ```js\n> const x = 2;\n> ```\n>\n> ```chart\n> {"title":"График","summary":"Прямая","points":[[0,0],[1,1]]}\n> ```\n\n[ref]: https://example.com';
  const node=callouts(source)[0];
  for(const kind of ['list','strong','link','math','table','code']) assert.ok(types(node.children).includes(kind),kind);
  assert.ok(JSON.stringify(node).includes('https://example.com'));
  assert.ok(node.children.some(n=>n.type==='code' && n.lang==='chart'));
  assert.ok(renderMathHtml('x=\\frac{a^2+b^2}{2ab}',true));
});

test('ordinary and malformed messages retain their old node types; code markers are literal', () => {
  for(const source of ['> Обычная цитата.','> **Важно:** Старое оформление.','> [Непонятно]\n> Текст.','> [Важ','> [Ответ]без пробела']) {
    assert.equal(callouts(source).length,0,source);
    assert.equal(parseRichText(source)[0].type,'blockquote');
  }
  assert.equal(callouts('```text\n> [Ответ]\n> 2\n```').length,0);
  assert.equal(parseRichText('Важно: правило.')[0].type,'paragraph');
  assert.equal(parseRichText('> [Ответ]')[0].type,'callout');
  assert.equal(callouts('> [Ответ]\n> Незакрытый ответ')[0].children.length,1);
});

test('callout text cannot enable HTML, script, unsafe links or trusted KaTeX', () => {
  const node=callouts('> [Ошибка] <img onerror="alert(1)">\n> <script>alert(1)</script>\n> [ссылка](javascript:alert(1))')[0];
  assert.ok(JSON.stringify(node).includes('script'));
  assert.ok(!types(node).includes('link'));
  assert.ok(!types(node).includes('html'));
});

test('every streaming prefix matches full Markdown and never throws', () => {
  const samples=[
    '> [Важно] ОДЗ\n> Не равен нулю.\n>\n> \\[x=\\frac{1}{a}\\]\n>\n> - Первый\n> - Второй\n\n> [Ответ]\n> \\(x=2\\).\n\nОбычный текст.',
    '> [Пример]\n> ```js\n> const x = 2;\n> ```\n>\n> Продолжение.',
    '> [Информация]\n> | A | B |\n> |---|---|\n> | 1 | 2 |',
  ];
  for(const source of samples) {
    const parse=createStreamingRichTextParser();
    for(let end=1;end<=source.length;end++) assert.deepEqual(parse(source.slice(0,end)),parseRichText(source.slice(0,end)));
  }
});

test('completed cards and finished math/list descendants retain identity as tail streams', () => {
  const parse=createStreamingRichTextParser();
  const prefix='> [Ответ]\n> \\[x=2\\]\n>\n> - Проверено\n>\n> Кон';
  const a=parse(prefix),b=parse(prefix+'ец.');
  assert.equal(a[0].type,'callout');assert.equal(b[0].type,'callout');
  if(a[0].type==='callout' && b[0].type==='callout') {
    assert.equal(a[0].children[0],b[0].children[0]);
    assert.equal(a[0].children[1],b[0].children[1]);
  }
  const c=parse(prefix+'ец.\n\nОбычный'),d=parse(prefix+'ец.\n\nОбычный текст.');
  assert.equal(c[0],d[0]);
});
