import type { Model } from '@/types';

/* =============================================================================
   Available AI models.

   This is fixture data for `MockWristMindService.models.list()`. Components
   never import it: model lists always arrive through the service, so the real
   backend can change them without a frontend release.
   ========================================================================== */

export const SEED_MODELS: Model[] = [
  {
    id: 'gpt-4o',
    name: 'GPT-4o',
    provider: 'OpenAI',
    context_window: 128_000,
    description: 'Баланс качества и скорости. Уверенно работает с изображениями и таблицами.',
    capabilities: ['vision', 'tools'],
  },
  {
    id: 'gpt-4o-mini',
    name: 'GPT-4o mini',
    provider: 'OpenAI',
    context_window: 128_000,
    description: 'Быстрая модель для коротких вопросов и черновых ответов.',
    capabilities: ['vision', 'fast'],
  },
  {
    id: 'claude-3-7-sonnet',
    name: 'Claude 3.7 Sonnet',
    provider: 'Anthropic',
    context_window: 200_000,
    description: 'Сильна в длинных документах и пошаговых рассуждениях.',
    capabilities: ['vision', 'tools', 'reasoning'],
  },
  {
    id: 'claude-3-5-haiku',
    name: 'Claude 3.5 Haiku',
    provider: 'Anthropic',
    context_window: 200_000,
    description: 'Самая быстрая в линейке Anthropic, хорошо держит инструкции.',
    capabilities: ['fast'],
  },
  {
    id: 'gemini-2-flash',
    name: 'Gemini 2.0 Flash',
    provider: 'Google',
    context_window: 1_000_000,
    description: 'Огромное окно контекста, подходит для больших баз знаний.',
    capabilities: ['vision', 'fast'],
  },
  {
    id: 'qwen2-5-vl-72b',
    name: 'Qwen2.5-VL 72B',
    provider: 'Локальный кластер',
    context_window: 128_000,
    description: 'Локальный запуск: данные не покидают контур. Сильный vision-разбор.',
    capabilities: ['vision', 'local'],
  },
  {
    id: 'llama-3-3-70b',
    name: 'Llama 3.3 70B',
    provider: 'Локальный кластер',
    context_window: 128_000,
    description: 'Локальная текстовая модель для чувствительных баз знаний.',
    capabilities: ['local', 'tools'],
  },
];
;

/** Provider for a model id; used to denormalise message metadata. */
export function providerForModel(modelId: string | null | undefined): string | null {
  if (!modelId) return null;
  return SEED_MODELS.find((model) => model.id === modelId)?.provider ?? null;
}
