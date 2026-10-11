import { compileExpression } from './mathExpression.ts';
export type ChartFunction = { expression: string; label: string; domain?: [number, number] };
export type AnswerChart = { title: string; summary: string; points: [number, number][]; functions?: ChartFunction[] };
/** Recover an unfenced chart envelope without treating ordinary JSON as a chart. */
export function extractLooseChart(source: string): { value: string; tail: string } | null {
  const text = source.trimStart();
  if (!/^\{\s*"title"\s*:/.test(text) || !/"summary"\s*:/.test(text)
    || !/"(?:points|functions)"\s*:/.test(text)) return null;
  let depth = 0, quoted = false, escaped = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (escaped) escaped = false;
      else if (c === '\\') escaped = true;
      else if (c === '"') quoted = false;
    } else if (c === '"') quoted = true;
    else if (c === '{') depth++;
    else if (c === '}' && --depth === 0) return { value: text.slice(0, i + 1), tail: text.slice(i + 1) };
  }
  return { value: text, tail: '' };
}
/** Legacy points remain valid; optional functions use a bounded arithmetic grammar. */
export function parseAnswerChart(source: string): AnswerChart | null {
  if (source.length > 100_000) return null;
  try {
    const value = JSON.parse(source);
    if (!value || typeof value.title !== 'string' || typeof value.summary !== 'string'
      || !Array.isArray(value.points) || value.points.length < 2 || value.points.length > 500) return null;
    if (!value.points.every((p: unknown) => Array.isArray(p) && p.length === 2
      && p.every((v) => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= 1e12))) return null;
    const points = (value.points as [number, number][]).slice().sort((a, b) => a[0] - b[0]);
    if (points[0][0] === points[points.length - 1][0]) return null;
    let functions: ChartFunction[] | undefined;
    if (value.functions !== undefined) {
      if (!Array.isArray(value.functions) || !value.functions.length || value.functions.length > 6) return null;
      functions = value.functions.map((f: unknown) => {
        if (!f || typeof f !== 'object' || !('expression' in f) || typeof f.expression !== 'string') throw new Error('expression');
        compileExpression(f.expression);
        const domain = 'domain' in f ? f.domain : undefined;
        if (domain !== undefined && (!Array.isArray(domain) || domain.length !== 2 || !domain.every(n => typeof n === 'number' && Number.isFinite(n) && Math.abs(n) <= 1e12) || domain[0] >= domain[1])) throw new Error('domain');
        return { expression: f.expression, label: 'label' in f && typeof f.label === 'string' ? f.label.slice(0, 80) : f.expression, ...(domain ? {domain: domain as [number,number]} : {}) };
      });
    }
    return { title: value.title.slice(0, 160), summary: value.summary.slice(0, 1000), points, ...(functions ? { functions } : {}) };
  } catch { return null; }
}

/** Readable 1/2/5 decade grid steps, recomputed for the visible domain. */
export function chartTicks(min: number, max: number, target = 5): number[] {
  const raw = (max - min) / target;
  const power = 10 ** Math.floor(Math.log10(raw));
  const fraction = raw / power;
  const step = (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * power;
  if (!Number.isFinite(step) || step <= 0) return [min, max];
  const start = Math.ceil(min / step - 1e-10);
  const end = Math.floor(max / step + 1e-10);
  return Array.from({length: Math.max(0, Math.min(12, end - start + 1))}, (_, index) => {
    const tick = Number(((start + index) * step).toPrecision(12));
    return Math.abs(tick) < step * 1e-10 ? 0 : tick;
  });
}
