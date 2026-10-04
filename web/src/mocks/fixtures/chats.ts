import type { Chat, Message, MessagePhase, MessageRole, MessageSource } from '@/types';
import { HOUR, NOW } from './random';
import { SEED_MODES } from './modes';
import { SEED_SOURCE_CONTENT, SEED_SOURCES } from './sources';
import { providerForModel } from './models';

/* =============================================================================
   Chats and message history.
   ========================================================================== */

const citation = (
  sourceId: string,
  chunkIndex: number,
  relevance: number,
): MessageSource => {
  const source = SEED_SOURCES.find((item) => item.id === sourceId);
  const chunks = SEED_SOURCE_CONTENT[sourceId]?.chunks ?? [];
  const chunk = chunks[chunkIndex] ?? chunks[0];
  return {
    id: `cit_${sourceId}_${chunkIndex}`,
    source_id: sourceId,
    source_title: source?.title ?? 'Источник',
    chunk_index: chunk?.index ?? 0,
    page: chunk?.page ?? 0,
    snippet: chunk?.text.slice(0, 180) ?? '',
    relevance,
  };
};

interface ChatMessageSpec {
  role: MessageRole;
  content: string;
  sources?: MessageSource[];
  timings_total_ms?: number;
  model_id?: string;
}

interface ChatSpec {
  id: string;
  title: string;
  mode_id: string | null;
  ageHours: number;
  pinned?: boolean;
  messages: ChatMessageSpec[];
}

const CHAT_SPECS: ChatSpec[] = [
  {
    id: 'chat_release_window',
    title: 'Окно релиза и условия отката',
    mode_id: 'mode_work',
    ageHours: 3,
    pinned: true,
    messages: [
      {
        role: 'user',
        content: 'Какое окно релиза у нас сейчас и при каких метриках срабатывает автоматический откат?',
      },
      {
        role: 'assistant',
        timings_total_ms: 6420,
        model_id: 'claude-3-7-sonnet',
        sources: [citation('src_release_policy', 2, 0.94), citation('src_release_policy', 5, 0.81)],
        content: `Заморозка кода — среда, 18:00 МСК; окно выкатки открывается в четверг утром после закрытия чек-листа.

**Поэтапная выкатка:** 5% → 25% → 100% трафика с паузой не менее 20 минут между этапами.

**Автоматический откат срабатывает, если:**
- доля ошибок 5xx превышает 1,5% в течение 5 минут;
- p95 задержки превышает 800 мс.

Ручной откат — \`wm release rollback --to <version>\`. Команда переключает трафик на предыдущий стабильный образ и не удаляет новый: диагностика продолжается на канареечном стенде.

Источники: «Регламент релизов и откатов», стр. 3 и стр. 6.`,
      },
      {
        role: 'user',
        content: 'А сколько исключений из заморозки допустимо?',
      },
      {
        role: 'assistant',
        timings_total_ms: 3110,
        model_id: 'claude-3-7-sonnet',
        sources: [citation('src_release_policy', 3, 0.89)],
        content: `Больше трёх исключений в одном релизном цикле — релиз переносится автоматически. Каждое исключение оформляется задачей с меткой \`release-exception\` и согласуется релиз-менеджером.

Также помню: исправления после заморозки допускаются только для блокирующих дефектов.

Источник: «Регламент релизов и откатов», стр. 2.`,
      },
    ],
  },
  {
    id: 'chat_bayes',
    title: 'Формула Байеса: разбор задачи с урнами',
    mode_id: 'mode_study',
    ageHours: 7,
    pinned: true,
    messages: [
      { role: 'user', content: 'Объясни формулу Байеса на примере двух урн. Почему нельзя просто переставить вероятности местами?' },
      {
        role: 'assistant',
        timings_total_ms: 7840,
        model_id: 'gpt-4o',
        sources: [citation('src_probability', 6, 0.96), citation('src_probability', 7, 0.83)],
        content: `Короткий ответ: потому что условные вероятности P(A|B) и P(B|A) описывают разные вопросы и совпадают только при равных безусловных вероятностях.

**Разбор по шагам.** Пусть есть две урны. В первой 3 белых и 7 чёрных шаров, во второй 6 белых и 4 чёрных. Урна выбирается случайно, с вероятностью 0,5.

1. Гипотезы: H₁ — выбрана первая урна, H₂ — вторая. P(H₁) = P(H₂) = 0,5.
2. Правдоподобия: P(Б|H₁) = 0,3; P(Б|H₂) = 0,6.
3. Полная вероятность белого шара: P(Б) = 0,5·0,3 + 0,5·0,6 = 0,45.
4. Апостериорная вероятность первой урны: P(H₁|Б) = 0,15 / 0,45 = 1/3.

**Типичная ошибка** — поменять местами априорную и апостериорную вероятности. Здесь P(H₁) = 0,5, а P(H₁|Б) ≈ 0,33: наблюдение изменило нашу уверенность.

**Вопрос для самопроверки:** как изменится ответ, если урна выбирается не поровну, а с вероятностью 0,8 в пользу первой?`,
      },
    ],
  },
  {
    id: 'chat_kbju',
    title: 'Сколько белка добираю на неделе',
    mode_id: 'mode_health',
    ageHours: 20,
    messages: [
      { role: 'user', content: 'Посчитай по таблице КБЖУ, выхожу ли я на 160 г белка в день.' },
      {
        role: 'assistant',
        timings_total_ms: 4260,
        model_id: 'gemini-2-flash',
        sources: [citation('src_nutrition', 0, 0.92)],
        content: `По таблице среднее значение — 154 г белка в день при цели 160 г. Отставание около 4%, то есть почти в пределах допустимого отклонения.

**Где просадка:** вторник (128 г) и суббота (131 г) — оба дня без отдельного белкового перекуса.

**Что добавить, не меняя калорийность:** 150 г творога 5% во вторник (+27 г белка) и 120 г греческого йогурта в субботу (+12 г). Калорийность вырастет незначительно, жиры останутся в пределах цели.

Источник: «Таблица КБЖУ на неделю».`,
      },
    ],
  },
  {
    id: 'chat_rag_ranking',
    title: 'Как считается итоговый вес при поиске',
    mode_id: 'mode_dev',
    ageHours: 31,
    messages: [
      { role: 'user', content: 'Как в нашем RAG-пайплайне объединяются векторный и полнотекстовый поиск?' },
      {
        role: 'assistant',
        timings_total_ms: 5310,
        model_id: 'qwen2-5-vl-72b',
        sources: [citation('src_rag_architecture', 4, 0.91), citation('src_rag_architecture', 5, 0.88)],
        content: `Комбинированная стратегия: результаты векторного поиска и полнотекстового поиска объединяются взвешенным ранжированием.

- Вес полнотекстового поиска **выше** для запросов с точными терминами — артикулы, версии, аббревиатуры.
- Для развёрнутых вопросов приоритет отдаётся **векторной близости**.
- После первичного отбора выполняется **переранжирование**, которое отсеивает фрагменты с высокой векторной близостью, но низкой смысловой релевантностью.
- Финальный контекст ограничен бюджетом **12 000 токенов**; избыточные кандидаты отбрасываются по итоговому весу с записью в журнал.

Изоляция баз знаний между режимами обеспечивается фильтром по идентификатору режима, поэтому фрагменты других режимов в выдачу не попадают.

Источник: «Архитектура RAG-пайплайна», стр. 5–6.`,
      },
    ],
  },
  {
    id: 'chat_dishwasher_salt',
    title: 'Соль в посудомойке',
    mode_id: 'mode_smart-home',
    ageHours: 52,
    messages: [
      { role: 'user', content: 'Как часто нужно добавлять соль?' },
      {
        role: 'assistant',
        timings_total_ms: 2380,
        model_id: 'gpt-4o-mini',
        sources: [citation('src_dishwasher', 1, 0.87)],
        content: `Ориентир — примерно раз в месяц, если жёсткость воды выше 7 градусов. Точный момент подскажет индикатор на панели: он загорается, когда соль заканчивается.

Перед первым включением проверьте жёсткость воды и заполните отсек соли.

Источник: «Инструкция: посудомоечная машина», стр. 2.`,
      },
    ],
  },
  {
    id: 'chat_quick_onboarding',
    title: 'Что успеть в первую неделю на новом проекте',
    mode_id: null,
    ageHours: 74,
    messages: [
      { role: 'user', content: 'Я вышел на новый проект. Что важно успеть за первую неделю?' },
      {
        role: 'assistant',
        timings_total_ms: 5120,
        model_id: 'gpt-4o',
        content: `Универсальный каркас первой недели, если нет внутреннего регламента:

1. **Доступы.** Выписать всё, без чего нельзя работать: репозитории, стенды, логи, панель администратора. Оформлять заявки в первый же день.
2. **Карта системы.** Попросить схему сервисов и пройти по ней вживую, а не только на бумаге.
3. **Локальный запуск.** Поднять окружение и получить зелёные тесты. Это главный маркер, что вы не заблокированы.
4. **Одна маленькая задача целиком.** Не обязательно сложная — важно пройти полный цикл: код, ревью, тесты, выкатка на стенд.
5. **Договорённости.** Зафиксировать, где задавать вопросы, кто наставник и в какие часы команда на связи.

Если регламент онбординга в компании есть — он важнее этого списка: там указаны сроки и ответственные.`,
      },
    ],
  },
  {
    id: 'chat_quick_shopping',
    title: 'Список покупок на выходные',
    mode_id: null,
    ageHours: 96,
    messages: [
      { role: 'user', content: 'Собери список покупок на выходные, чтобы хватило на заготовки.' },
      {
        role: 'assistant',
        timings_total_ms: 2990,
        model_id: 'gpt-4o-mini',
        content: `Под заготовки на неделю из базовых компонентов:

**Белок:** куриное филе 1,5 кг, лосось 600 г, яйца 20 шт., творог 5% 1 кг.
**Крупы и гарниры:** булгур 800 г, рис 800 г, гречка 700 г.
**Овощи:** болгарский перец 6 шт., кабачки 3 шт., морковь 1 кг, лук 1 кг, помидоры черри 500 г, брокколи 4 головки.
**Для соусов:** греческий йогурт 800 г, томаты в собственном соку 3 банки, лимон 4 шт., чеснок.
**Мелочи:** оливковое масло, паприка, кумин, соль, бумажные полотенца.

Контейнеры для хранения проверьте заранее: стекло переносит и заморозку, и микроволновку.`,
      },
    ],
  },
  {
    id: 'chat_empty_arch',
    title: 'Вопросы по архитектуре',
    mode_id: 'mode_dev',
    ageHours: 2,
    messages: [],
  },
  {
    id: 'chat_empty_week',
    title: 'План на неделю',
    mode_id: 'mode_work',
    ageHours: 1,
    messages: [],
  },
];;

const FULL_PIPELINE: MessagePhase[] = [
  'queued',
  'context',
  'search_query',
  'searching',
  'reviewing_sources',
  'opening_source',
  'generating',
];

const DIRECT_PIPELINE: MessagePhase[] = ['queued', 'context', 'generating'];

/** Rough token accounting so message metadata is not empty in the demo. */
function estimateUsage(content: string, sources: MessageSource[]) {
  const completion = Math.round(content.length / 3);
  const prompt = 480 + sources.length * 210 + Math.round(content.length / 12);
  return {
    prompt_tokens: prompt,
    completion_tokens: completion,
    total_tokens: prompt + completion,
  };
}

interface MaterializedChat {
  chat: Chat;
  messages: Message[];
}

function materializeChat(spec: ChatSpec): MaterializedChat {
  const base = new Date(NOW - spec.ageHours * HOUR).getTime();
  const mode = SEED_MODES.find((item) => item.id === spec.mode_id);

  const messages: Message[] = spec.messages.map((m, i) => {
    const createdAt = new Date(base + i * 90_000).toISOString();
    const sources = m.sources ?? [];
    const usesKnowledgeBase = sources.length > 0;
    const modelId = m.role === 'assistant' ? (m.model_id ?? null) : null;

    return {
      id: `msg_${spec.id}_${i}`,
      chat_id: spec.id,
      role: m.role,
      content: m.content,
      status: 'complete',
      provider: providerForModel(modelId),
      model_id: modelId,
      usage: m.role === 'assistant' ? estimateUsage(m.content, sources) : null,
      timings:
        m.role === 'assistant'
          ? { total_ms: m.timings_total_ms ?? null, first_token_ms: 240 }
          : null,
      sources,
      phases: m.role === 'assistant' ? (usesKnowledgeBase ? FULL_PIPELINE : DIRECT_PIPELINE) : [],
      created_at: createdAt,
    };
  });

  const last = messages[messages.length - 1];

  return {
    chat: {
      id: spec.id,
      mode_id: spec.mode_id,
      mode_name: mode?.name ?? null,
      mode_deleted: false,
      title: spec.title,
      created_at: new Date(base).toISOString(),
      updated_at: last ? last.created_at : new Date(base).toISOString(),
      deleted_at: null,
      pinned: spec.pinned ?? false,
    },
    messages,
  };
}

const MATERIALIZED = CHAT_SPECS.map(materializeChat);

export const SEED_CHATS: Chat[] = MATERIALIZED.map((entry) => entry.chat);

export const SEED_MESSAGES: Record<string, Message[]> = Object.fromEntries(
  MATERIALIZED.map((entry) => [entry.chat.id, entry.messages]),
);

