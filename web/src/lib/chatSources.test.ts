import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import {
  chatSourceCards,
  countChatSourceKinds,
  filterChatSourceCards,
  messageSourceCards,
  normalizeChatSources,
  normalizeSourceUrl,
  sourceMonogram,
  type MessageSourceContext,
} from './chatSources.ts';
import { extractLegacySources } from './webSources.ts';

/* Run with:  npm test   (node --test --experimental-strip-types src/lib/) */

test('a chat without sources produces no cards', () => {
  assert.deepEqual(chatSourceCards(normalizeChatSources({ working: [], referenced: [] })), []);
  assert.deepEqual(chatSourceCards(undefined), []);
  assert.deepEqual(chatSourceCards(null), []);
});

test('a chat with referenced sources only lists them in order', () => {
  const cards = chatSourceCards(
    normalizeChatSources({
      working: [],
      referenced: [
        {
          id: 'r1',
          title: 'Колобок — Чудесная страна',
          url: 'https://chudesnayastrana.ru/kolobok',
          snippet: 'Жили-были старик со старухой…',
          retrieved_at: '2026-10-02T10:00:00Z',
          message_id: 'm1',
        },
      ],
    }),
  );

  assert.equal(cards.length, 1);
  assert.equal(cards[0].kind, 'referenced');
  assert.equal(cards[0].title, 'Колобок — Чудесная страна');
  assert.equal(cards[0].domain, 'chudesnayastrana.ru');
  assert.equal(cards[0].messageId, 'm1');
});

test('a working source exposes its origin URL, domain and origin title', () => {
  const cards = chatSourceCards(
    normalizeChatSources({
      working: [
        {
          id: 'w1',
          title: 'Колобок — русская народная сказка',
          origin_url: 'https://deti-online.com/skazki/kolobok/',
          origin_title: 'Колобок',
          status: 'ready',
          created_at: '2026-10-02T09:00:00Z',
        },
      ],
      referenced: [],
    }),
  );

  assert.equal(cards.length, 1);
  assert.equal(cards[0].kind, 'working');
  assert.equal(cards[0].url, 'https://deti-online.com/skazki/kolobok/');
  assert.equal(cards[0].domain, 'deti-online.com');
  assert.equal(cards[0].originTitle, 'Колобок');
  assert.equal(cards[0].status, 'ready');
  // The extracted content is never part of a card.
  assert.equal(cards[0].snippet, null);
  assert.equal(sourceMonogram(cards[0]), 'D');
});

test('a working source suppresses the referenced card with the same URL', () => {
  const cards = chatSourceCards(
    normalizeChatSources({
      working: [
        {
          id: 'w1',
          title: 'Колобок',
          origin_url: 'https://deti-online.com/skazki/kolobok/',
          origin_title: null,
          status: 'ready',
          created_at: null,
        },
      ],
      referenced: [
        {
          id: 'r1',
          title: 'Колобок',
          url: 'https://deti-online.com/skazki/kolobok',
          snippet: null,
          retrieved_at: null,
          message_id: 'm1',
        },
      ],
    }),
  );

  assert.equal(cards.length, 1);
  assert.equal(cards[0].kind, 'working');
});

test('all chat sources are a unique combined list ordered working first', () => {
  const cards = chatSourceCards(
    normalizeChatSources({
      working: [
        {
          id: 'w1',
          title: 'Вики',
          origin_url: 'https://ru.wikipedia.org/wiki/Колобок',
          origin_title: null,
          status: 'ready',
          created_at: null,
        },
      ],
      referenced: [
        {
          id: 'r1',
          title: 'Дубль',
          url: 'https://ru.wikipedia.org/wiki/Колобок',
          snippet: null,
          retrieved_at: null,
          message_id: null,
        },
        {
          id: 'r2',
          title: 'Первый',
          url: 'https://a.example/page',
          snippet: null,
          retrieved_at: null,
          message_id: 'm1',
        },
        {
          id: 'r3',
          title: 'Повтор в другом ответе',
          url: 'https://a.example/page/',
          snippet: null,
          retrieved_at: null,
          message_id: 'm2',
        },
      ],
    }),
  );

  assert.deepEqual(
    cards.map((card) => `${card.kind}:${card.title}`),
    ['working:Вики', 'referenced:Первый'],
  );
  assert.deepEqual(countChatSourceKinds(cards), { all: 2, working: 1, referenced: 1 });
});

test('per-answer mode returns only that answer records', () => {
  const sources = normalizeChatSources({
    working: [
      {
        id: 'w1',
        title: 'Колобок',
        origin_url: 'https://deti-online.com/kolobok',
        origin_title: null,
        status: 'ready',
        created_at: null,
      },
      {
        id: 'w2',
        title: 'Репка',
        origin_url: 'https://deti-online.com/repka',
        origin_title: null,
        status: 'ready',
        created_at: null,
      },
    ],
    referenced: [
      {
        id: 'r1',
        title: 'Другой ответ',
        url: 'https://other.example/x',
        snippet: null,
        retrieved_at: null,
        message_id: 'm2',
      },
    ],
  });

  const message: MessageSourceContext = {
    id: 'm1',
    web_sources: [
      { id: 'r0', title: 'Этот ответ', url: 'https://answer.example/one', retrieved_at: '2026-10-02T10:00:00Z' },
    ],
    timings: { local_context: { working_titles: ['Колобок'] } },
  };

  const cards = messageSourceCards(message, sources);

  assert.deepEqual(
    cards.map((card) => `${card.kind}:${card.title}`),
    ['working:Колобок', 'referenced:Этот ответ'],
  );
  assert.ok(cards.every((card) => card.messageId === 'm1' || card.kind === 'working'));
});

test('per-answer mode keeps a working title the chat index no longer has', () => {
  const cards = messageSourceCards(
    { id: 'm9', timings: { local_context: { working_titles: ['Пропавший источник'] } } },
    { working: [], referenced: [] },
  );

  assert.equal(cards.length, 1);
  assert.equal(cards[0].kind, 'working');
  assert.equal(cards[0].title, 'Пропавший источник');
  assert.equal(cards[0].url, null);
});

test('a page saved during the answer is shown as saved material', () => {
  const sources = normalizeChatSources({
    working: [{ id: 'saved', title: 'Колобок', origin_url: 'https://example.test/kolobok', status: 'ready' }],
    referenced: [],
  });
  const cards = messageSourceCards({
    id: 'answer',
    web_sources: [{ id: 'page', title: 'Сказка', url: 'https://example.test/kolobok' }],
  }, sources);

  assert.deepEqual(cards.map((card) => `${card.kind}:${card.title}`), ['working:Колобок']);
});

test('per-answer mode tolerates old messages without structured metadata', () => {
  assert.deepEqual(messageSourceCards({ id: 'old' }, undefined), []);
  assert.deepEqual(messageSourceCards(undefined, undefined), []);
  assert.deepEqual(messageSourceCards(null, null), []);
});

test('filters apply within the given card set', () => {
  const cards = chatSourceCards(
    normalizeChatSources({
      working: [
        {
          id: 'w1',
          title: 'Working',
          origin_url: 'https://wi.example/a',
          origin_title: null,
          status: 'ready',
          created_at: null,
        },
      ],
      referenced: [
        { id: 'r1', title: 'Ref', url: 'https://re.example/b', snippet: null, retrieved_at: null, message_id: null },
      ],
    }),
  );

  assert.equal(filterChatSourceCards(cards, 'all').length, 2);
  assert.deepEqual(filterChatSourceCards(cards, 'working').map((card) => card.id), ['w1']);
  assert.deepEqual(filterChatSourceCards(cards, 'referenced').map((card) => card.id), ['r1']);
});

test('normalizeChatSources drops malformed entries instead of crashing', () => {
  const sources = normalizeChatSources({
    working: [null, 'nope', {}, { id: 'w1', origin_url: 'https://x.example/a' }],
    referenced: [{ id: 'r1' }, { id: 'r2', url: '  ' }],
  });

  assert.equal(sources.working.length, 1);
  assert.equal(sources.working[0].title, 'https://x.example/a');
  assert.equal(sources.referenced.length, 0);
  assert.deepEqual(normalizeChatSources(null), { working: [], referenced: [] });
});

test('URL comparison ignores a trailing slash, scheme case and fragment', () => {
  assert.equal(
    normalizeSourceUrl('https://Example.COM/page/#section'),
    normalizeSourceUrl('https://example.com/page'),
  );
});

test('the legacy Markdown source block is stripped from an answer', () => {
  const answer = [
    'Колобок — это русская народная сказка.',
    '',
    '**Использованные источники**',
    '- [Колобок — русская народная сказка](https://deti-online.com/skazki/kolobok/)',
    '- [Колобок — Чудесная страна](https://chudesnayastrana.ru/kolobok)',
  ].join('\n');

  const result = extractLegacySources(answer);

  assert.equal(result.content, 'Колобок — это русская народная сказка.');
  assert.deepEqual(
    result.sources.map((source) => source.url),
    ['https://deti-online.com/skazki/kolobok/', 'https://chudesnayastrana.ru/kolobok'],
  );
});

test('a referenced card resolves the exact origin URL for its link', () => {
  const url = 'https://chudesnayastrana.ru/kolobok?from=chat';
  const cards = chatSourceCards(
    normalizeChatSources({
      working: [],
      referenced: [
        { id: 'r1', title: 'Колобок', url, snippet: null, retrieved_at: null, message_id: null },
      ],
    }),
  );

  assert.equal(cards[0].url, url);
});
