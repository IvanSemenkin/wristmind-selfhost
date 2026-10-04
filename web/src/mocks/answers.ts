import type { KnowledgeSource, MessageSource, Mode, SourceChunk } from '@/types';
import { createId } from '@/lib/id';

/* =============================================================================
   Mock answer composition.

   Lives in the mock layer: it fabricates a plausible, source-grounded answer
   from the mode's own knowledge base so the prototype reads like the real
   product. `ApiWristMindService` never touches this file.
   ========================================================================== */

export interface AnswerCandidate {
  source: KnowledgeSource;
  chunks: SourceChunk[];
}

export interface ComposedAnswer {
  content: string;
  sources: MessageSource[];
  model_id: string | null;
  provider: string | null;
}

const pick = <T,>(items: T[], seed: number): T => items[Math.abs(seed) % items.length];

/** Splits a chunk into sentences usable as bullet points. */
function sentencesOf(text: string): string[] {
  return text
    .replace(/\n+/g, ' ')
    .split(/(?<=[.!?])\s+/)
    .map((sentence) => sentence.trim())
    .filter((sentence) => sentence.length > 40 && sentence.length < 260);
}

const MODE_FRAMING: Record<string, string> = {
  mode_work: 'Ниже — выдержки из внутренних документов команды, на которые можно ссылаться в задаче.',
  mode_study: 'Разберу по шагам, опираясь на конспект и учебник из базы знаний режима.',
  mode_health:
    'Смотрю в ваши собственные материалы — план тренировок и записи. Это не медицинская рекомендация.',
  mode_smart_home: 'Ниже — выдержка из инструкции, чтобы не пересказывать её своими словами.',
  mode_dev: 'Опираюсь на документацию платформы. Ниже — то, что она утверждает напрямую.',
};

const MODE_CAVEAT: Record<string, string> = {
  mode_work:
    'Если речь про конкретный релиз, уточните версию и среду — часть требований зависит от контура.',
  mode_study: 'Проверьте себя: сможете ли вы воспроизвести шаг 2, не подглядывая в конспект?',
  mode_health:
    'Перед изменением нагрузки стоит обсудить план со специалистом, если есть ограничения по здоровью.',
  mode_smart_home: 'Перед шагами с водой или электричеством отключите прибор от сети.',
  mode_dev: 'Поведение части методов зависит от версии API — сверяйтесь с префиксом в пути запроса.',
};

interface ComposeOptions {
  question: string;
  mode: Mode | null;
  candidates: AnswerCandidate[];
  /** Extra context the answer should acknowledge. */
  web_search: boolean;
  web_research: boolean;
}

function quickAnswer(question: string, webSearch: boolean, webResearch: boolean): string {
  const trimmed = question.trim().replace(/\s+/g, ' ').slice(0, 90);
  const webNote = webSearch
    ? '\n\nРежим без своей базы знаний, поэтому я бы опирался на открытые источники: проверяйте актуальность на дату запроса.'
    : '\n\nЕсли привязать вопрос к режиму с базой знаний, я смогу отвечать по вашим документам, а не общими словами.';
  const researchNote = webResearch
    ? '\n\nЗапущен расширенный поиск: я бы сверил минимум три независимых источника и отметил расхождения.'
    : '';

  return `Коротко и без привязки к базе знаний — это универсальный чат, поэтому отвечаю общими соображениями.

**Как я бы подошёл к вопросу «${trimmed}»**

1. **Сформулировать результат.** Что должно измениться, чтобы задача считалась решённой — в одном предложении.
2. **Отделить известное от неизвестного.** Всё, что можно проверить документально, проверяется до принятия решения.
3. **Сузить до одного шага.** Первый шаг должен быть выполним за один подход и давать наблюдаемый результат.
4. **Зафиксировать критерий.** Заранее решить, по какому признаку вы поймёте, что двигаетесь не туда.

**Чего избегать:** распараллеливания на старте и решений, которые нельзя отменить.${webNote}${researchNote}`;
}

export function composeAnswer({
  question,
  mode,
  candidates,
  web_search: webSearch,
  web_research: webResearch,
}: ComposeOptions): ComposedAnswer {
  const usable = candidates.filter((candidate) => candidate.chunks.length > 0);

  if (!mode || usable.length === 0) {
    return {
      content: quickAnswer(question, webSearch, webResearch),
      sources: [],
      model_id: null,
      provider: null,
    };
  }

  const seed = question.length * 31 + mode.id.length;
  const primary = pick(usable, seed);
  const secondary = usable.length > 1 ? pick(usable, seed + 7) : null;

  const points: Array<{ sentence: string; page: number }> = [];
  for (const chunk of primary.chunks.slice(0, 4)) {
    for (const sentence of sentencesOf(chunk.text)) {
      if (points.length >= 4) break;
      if (points.some((point) => point.sentence === sentence)) continue;
      points.push({ sentence, page: chunk.page });
    }
    if (points.length >= 4) break;
  }

  const sources: MessageSource[] = [];
  const bodyPoints = points.map((point, index) => {
    const owner = index < 2 ? primary : (secondary ?? primary);
    const chunk = owner.chunks.find((item) => item.page === point.page) ?? owner.chunks[0];
    sources.push({
      id: createId('cit'),
      source_id: owner.source.id,
      source_title: owner.source.title,
      chunk_index: chunk.index,
      page: chunk.page,
      snippet: chunk.text.slice(0, 200),
      relevance: Math.max(0.62, 0.96 - index * 0.07),
    });
    return `- ${point.sentence} <sup>${owner.source.title}, стр. ${point.page + 1}</sup>`;
  });

  const framing = MODE_FRAMING[mode.id] ?? 'Ниже — то, что найдено в базе знаний режима.';
  const caveat = MODE_CAVEAT[mode.id] ?? 'Проверьте актуальность документа перед использованием.';
  const lead =
    points[0]?.sentence ??
    `В базе знаний режима «${mode.name}» есть материалы по этому вопросу, но прямой формулировки ответа в них нет.`;

  const webBlock = webResearch
    ? `

**Веб-исследование**

Дополнительно я бы сверил ответ с открытыми источниками: официальной документацией и датами публикаций. Расхождения между документами и веб-источниками стоит фиксировать отдельно.`
    : webSearch
      ? `

**Веб-поиск**

Кроме базы знаний запрошены открытые источники. Если документ в базе знаний старше веб-источника, приоритет у более свежего.`
      : '';

  const content = `${lead}

${framing}

${bodyPoints.join('\n')}

**Что стоит учесть**

${caveat}${webBlock}

Итого опираюсь на ${usable.length === 1 ? 'единственный готовый источник' : `${usable.length} готовых источника`} режима «${mode.name}».${
    secondary && secondary.source.id !== primary.source.id
      ? ` Отдельно полезен документ «${secondary.source.title}».`
      : ''
  }`;

  return {
    content,
    sources,
    model_id: mode.response_model_id,
    provider: null,
  };
}

/** Short chat title derived from the first user message. */
export function deriveChatTitle(text: string): string {
  const clean = text.trim().replace(/\s+/g, ' ');
  if (clean.length <= 52) return clean;
  return `${clean.slice(0, 52).replace(/[,;:.\s]+\S*$/, '')}…`;
}
