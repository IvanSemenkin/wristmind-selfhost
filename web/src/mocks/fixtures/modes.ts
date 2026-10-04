import type { Mode } from '@/types';
import { DAY, ago } from './random';

/* =============================================================================
   Modes.

   `visibleOnWatch` in the prototype maps to the API's `hidden_on_watch`, which
   is inverted: `hidden_on_watch === false` means the mode shows up on the watch.
   ========================================================================== */

interface ModeSpec {
  id: string;
  name: string;
  description: string;
  color: Mode['color'];
  response_model_id: string;
  hidden_on_watch: boolean;
  system_prompt: string;
  ageDays: number;
}

const MODE_SPECS: ModeSpec[] = [
  {
    id: 'mode_work',
    name: 'Рабочий ассистент',
    description:
      'Регламенты, встречи, статусы проектов и внутренняя документация команды WristMind.',
    color: 'blue',
    response_model_id: 'claude-3-7-sonnet',
    hidden_on_watch: false,
    ageDays: 148,
    system_prompt: `Ты — рабочий ассистент инженерной команды WristMind.

Правила:
1. Отвечай кратко и по делу, на русском языке.
2. Опирайся в первую очередь на базу знаний режима. Если данных нет — прямо скажи об этом.
3. Для каждого факта из документа указывай источник: название документа и страницу.
4. Если вопрос про релиз или инцидент — сначала уточни версию и среду.
5. Не выдумывай номера задач, версии и даты.`,
  },
  {
    id: 'mode_study',
    name: 'Учёба и конспекты',
    description: 'Лекции, учебники и семинарские конспекты. Разбор сложных тем по шагам.',
    color: 'emerald',
    response_model_id: 'gpt-4o',
    hidden_on_watch: false,
    ageDays: 96,
    system_prompt: `Ты — учебный помощник. Твоя задача — объяснять материал так, чтобы его можно было применить на практике.

Правила:
1. Сначала короткий ответ, затем разбор по шагам.
2. Приводи формулы в виде текста и поясняй каждую переменную.
3. Отмечай, какие страницы конспекта подтверждают вывод.
4. Если студент ошибся — объясни, где именно, без осуждения.
5. В конце предлагай один вопрос для самопроверки.`,
  },
  {
    id: 'mode_health',
    name: 'Здоровье и тренировки',
    description: 'План тренировок, питание, сон и расшифровка анализов. Данные с часов.',
    color: 'rose',
    response_model_id: 'gemini-2-flash',
    hidden_on_watch: false,
    ageDays: 61,
    system_prompt: `Ты — помощник по здоровому образу жизни. Ты не врач и не ставишь диагнозы.

Правила:
1. Всегда добавляй оговорку, что рекомендация не заменяет консультацию специалиста.
2. Опирайся на план тренировок и записи пользователя, а не на общие советы.
3. Формулируй рекомендации измеримо: подходы, повторы, темп, время.
4. Не комментируй лекарства и дозировки.
5. При жалобах на боль — рекомендуй обратиться к врачу.`,
  },
  {
    id: 'mode_smart-home',
    name: 'Дом и быт',
    description: 'Инструкции к технике, рецепты, списки покупок и бытовые мелочи.',
    color: 'amber',
    response_model_id: 'gpt-4o-mini',
    hidden_on_watch: true,
    ageDays: 34,
    system_prompt: `Ты — бытовой помощник. Отвечай максимально конкретно.

Правила:
1. Инструкции давай пошагово, нумерованным списком.
2. Указывай режимы, температуры и время в явном виде.
3. Если в вопросе есть цена или количество — считай точно.
4. Предупреждай о технике безопасности, если шаг связан с водой, газом или электричеством.`,
  },
  {
    id: 'mode_dev',
    name: 'Разработка',
    description: 'API WristMind, архитектура RAG-пайплайна и внутренние гайдлайны.',
    color: 'violet',
    response_model_id: 'qwen2-5-vl-72b',
    hidden_on_watch: true,
    ageDays: 122,
    system_prompt: `Ты — технический ассистент по платформе WristMind.

Правила:
1. Отвечай как инженер: версия API, эндпоинт, формат запроса и ответа.
2. Приводи примеры на TypeScript или curl.
3. Явно указывай ограничения, квоты и коды ошибок.
4. Если поведение зависит от версии — назови версию.
5. Не предлагай несуществующие эндпоинты: если в документации их нет, скажи об этом.`,
  },
];;

export const SEED_MODES: Mode[] = MODE_SPECS.map((spec) => ({
  id: spec.id,
  name: spec.name,
  description: spec.description,
  color: spec.color,
  icon: null,
  telegram_emoji_id: null,
  system_prompt: spec.system_prompt,
  response_model_id: spec.response_model_id,
  hidden_on_watch: spec.hidden_on_watch,
  created_at: ago(spec.ageDays * DAY),
  updated_at: ago(spec.ageDays * DAY * 0.18),
  deleted_at: null,
}));
