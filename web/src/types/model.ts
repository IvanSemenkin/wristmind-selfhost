/* =============================================================================
   Models — always fetched from the backend, never hardcoded in components.
   ========================================================================== */

export type ModelCapability = 'vision' | 'tools' | 'reasoning' | 'fast' | 'local';

export interface Model {
  id: string;
  name: string;
  provider: string;
  /** Token window advertised by the provider. */
  context_window: number;
  description: string;
  capabilities: ModelCapability[];
}

export const MODEL_CAPABILITY_LABELS: Record<ModelCapability, string> = {
  vision: 'Vision',
  tools: 'Инструменты',
  reasoning: 'Рассуждения',
  fast: 'Быстрая',
  local: 'Локальная',
};

export function findModel(models: Model[], id: string | null | undefined): Model | undefined {
  if (!id) return undefined;
  return models.find((model) => model.id === id);
}
