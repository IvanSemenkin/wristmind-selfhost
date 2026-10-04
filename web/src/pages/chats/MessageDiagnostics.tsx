import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Check, ChevronRight, Copy, ExternalLink } from 'lucide-react';
import { Badge, IconButton, Tooltip, useToast } from '@/components';
import type { Tone } from '@/components';
import { useCopyToClipboard } from '@/lib/hooks';
import type { Message, MessageTimings, MessageWebSource } from '@/types';
import styles from './MessageDiagnostics.module.css';

/* =============================================================================
   Message diagnostics

   Read-only view over the operational metadata the backend already records on
   an assistant message (`timings`, referenced web sources). It makes no
   network calls and never renders prompts, hidden reasoning, secrets or the
   body of fetched pages. Old messages with only `total_ms`/`first_token_ms`
   simply render nothing.
   ========================================================================== */

/* ---- Generic readers ------------------------------------------------------- */

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const asString = (value: unknown): string | null =>
  typeof value === 'string' && value.trim().length > 0 ? value : null;

const asNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

const asBoolean = (value: unknown): boolean | null =>
  typeof value === 'boolean' ? value : null;

const asStringArray = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.length > 0)
    : [];

/** First non-empty string among candidate keys, used for forward-compatible extras. */
const pickString = (source: Record<string, unknown> | null, keys: string[]): string | null => {
  if (!source) return null;
  for (const key of keys) {
    const value = asString(source[key]);
    if (value != null) return value;
  }
  return null;
};

const pickBoolean = (source: Record<string, unknown> | null, keys: string[]): boolean | null => {
  if (!source) return null;
  for (const key of keys) {
    const value = asBoolean(source[key]);
    if (value != null) return value;
  }
  return null;
};

const pickNumber = (source: Record<string, unknown> | null, keys: string[]): number | null => {
  if (!source) return null;
  for (const key of keys) {
    const value = asNumber(source[key]);
    if (value != null) return value;
  }
  return null;
};

/* ---- Presentation metadata ------------------------------------------------- */

const RETRIEVAL_TONES: Record<string, Tone> = {
  none: 'neutral',
  chat_sources: 'info',
  web: 'success',
  deep_web: 'warning',
};

const ROUTER_LABELS: Record<string, string> = {
  model: 'model',
  retry: 'retry',
  fallback: 'детерминированный fallback',
};

const ANCHOR_LABELS: Record<string, string> = {
  model: 'model',
  deterministic: 'детерминированный',
};

const yesNo = (value: boolean): string => (value ? 'да' : 'нет');

/** Compact duration for the collapsed line, e.g. `58.0s` / `820ms`. */
function shortDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/* ---- Data derivation ------------------------------------------------------- */

interface DiagnosticsModel {
  isResearch: boolean;
  queries: string[];
  searches: number | null;
  opened: number | null;
  referencedCount: number | null;
  /** Meaningful per-stage timings that actually exist. */
  stageTimings: Array<{ label: string; value: number }>;
  failures: Array<{ label: string; tone: Tone }>;
}

function isResearch(timings: MessageTimings | null): boolean {
  return timings?.research?.requested === true;
}

function collectStageTimings(timings: MessageTimings | null): Array<{ label: string; value: number }> {
  if (!timings) return [];
  const candidates: Array<[string, number | undefined]> = [
    ['router_ms', timings.router_ms],
    ['anchor_ms', timings.anchor_ms],
    ['local_retrieval_ms', timings.local_retrieval_ms],
    ['web_search_ms', timings.web_search_ms],
    ['open_ms', timings.open_ms],
    ['generation_ms', timings.generation_ms],
    ['review_ms', timings.review_ms],
    ['refine_ms', timings.refine_ms],
  ];
  return candidates
    .filter((entry): entry is [string, number] => typeof entry[1] === 'number' && Number.isFinite(entry[1]))
    .map(([label, value]) => ({ label, value }));
}

function collectFailures(timings: MessageTimings | null): Array<{ label: string; tone: Tone }> {
  const failures: Array<{ label: string; tone: Tone }> = [];
  if (!timings) return failures;
  if (timings.router_source === 'retry') failures.push({ label: 'Повторная маршрутизация (retry)', tone: 'warning' });
  if (timings.router_source === 'fallback') failures.push({ label: 'Детерминированный fallback', tone: 'warning' });

  const web = asRecord(timings.web_search);
  const research = asRecord(timings.research);
  const local = asRecord(timings.local_context);

  const webUnavailable =
    pickBoolean(web, ['unavailable', 'is_unavailable']) === true || asString(web?.error) != null;
  if (webUnavailable) failures.push({ label: 'Веб-поиск недоступен', tone: 'warning' });

  const openFailed =
    pickBoolean(web, ['open_failed', 'open_error']) === true ||
    (pickNumber(web, ['open_failed', 'failed_opens', 'open_errors']) ?? 0) > 0;
  if (openFailed) failures.push({ label: 'Не удалось открыть страницу', tone: 'warning' });

  const extractionFallback =
    pickBoolean(web, ['extraction_fallback', 'extraction_failed']) === true ||
    pickBoolean(local, ['extraction_fallback']) === true;
  if (extractionFallback) failures.push({ label: 'Резервный разбор страницы', tone: 'warning' });

  const timedOut =
    asBoolean(research?.timed_out) === true || asBoolean(web?.timed_out) === true;
  if (timedOut) failures.push({ label: 'Превышено время ожидания', tone: 'warning' });

  return failures;
}

function buildModel(message: Message): DiagnosticsModel {
  const timings = message.timings;
  const web = asRecord(timings?.web_search);
  const queries = asStringArray(web?.queries);
  const searches = asNumber(web?.searches) ?? (queries.length > 0 ? queries.length : null);
  const opened = asNumber(web?.opened_pages);
  const webSources = message.web_sources ?? [];
  const referencedCount =
    webSources.length > 0 ? webSources.length : (asNumber(web?.sources) ?? null);

  return {
    isResearch: isResearch(timings),
    queries,
    searches,
    opened,
    referencedCount,
    stageTimings: collectStageTimings(timings),
    failures: collectFailures(timings),
  };
}

/** True when the message carries anything worth opening the block for. */
export function hasMessageDiagnostics(message: Message): boolean {
  if ((message.web_sources?.length ?? 0) > 0) return true;
  const timings = message.timings;
  if (!timings) return false;
  return Object.keys(timings).some((key) => {
    if (key === 'total_ms' || key === 'first_token_ms') return false;
    const value = timings[key];
    if (value == null) return false;
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === 'object') return Object.keys(value as object).length > 0;
    return true;
  });
}

/** Compact one-line summary shown while collapsed. */
function collapsedLine(message: Message, model: DiagnosticsModel): string {
  const timings = message.timings;
  const parts: string[] = [model.isResearch ? 'RESEARCH' : 'AUTO'];
  if (timings?.route?.retrieval) parts.push(timings.route.retrieval);
  if (timings?.route?.task_type) parts.push(timings.route.task_type);
  if (model.searches != null && model.searches > 0) parts.push(`${model.searches} searches`);
  if (model.opened != null && model.opened > 0) parts.push(`${model.opened} open`);
  if (model.referencedCount != null && model.referencedCount > 0) parts.push(`${model.referencedCount} refs`);
  if (timings?.total_ms != null) parts.push(shortDuration(timings.total_ms));
  return parts.join(' · ');
}

/** Plain-text summary copied to the clipboard. `-` marks missing values. */
/**
 * How the backend assembled the local context. `full_sources` means the chat's
 * Working Sources were pinned whole, so the answer really read the entire text;
 * `hybrid` means only the most relevant chunks were selected.
 */
const CONTEXT_STRATEGY_LABELS: Record<string, string> = {
  full: 'целиком, без отбора',
  full_sources: 'рабочие источники целиком',
  hybrid: 'отбор по релевантности',
  none: 'материала нет',
  deleted_mode: 'режим удалён',
};

function buildSummary(message: Message, model: DiagnosticsModel): string {
  const timings = message.timings;
  const local = asRecord(timings?.local_context);
  const workingUsedKnown = Array.isArray(local?.working_titles);
  const reviewRounds = asNumber(asRecord(timings?.research)?.review_rounds);
  const webSources = message.web_sources;
  return [
    `Mode: ${model.isResearch ? 'RESEARCH' : 'AUTO'}`,
    `Route: ${timings?.route?.retrieval ?? '-'}`,
    `Task: ${timings?.route?.task_type ?? '-'}`,
    `Router: ${timings?.router_source ?? '-'}`,
    `Anchor: ${timings?.request_anchor?.mode ?? '-'}`,
    `Searches: ${model.searches ?? '-'}`,
    `Opened: ${model.opened ?? '-'}`,
    `Referenced: ${webSources ? webSources.length : '-'}`,
    `Working used: ${workingUsedKnown ? asStringArray(local?.working_titles).length : '-'}`,
    `Review rounds: ${reviewRounds ?? '-'}`,
    `Total: ${timings?.total_ms != null ? `${timings.total_ms} ms` : '-'}`,
  ].join('\n');
}

/* ---- Small presentational primitives --------------------------------------- */

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.section}>
      <h4 className={styles.sectionTitle}>{title}</h4>
      <div className={styles.sectionBody}>{children}</div>
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.row}>
      <span className={styles.rowLabel}>{label}</span>
      <span className={styles.rowValue}>{children}</span>
    </div>
  );
}

function ValueList({ values }: { values: string[] }) {
  if (values.length === 0) return null;
  return (
    <ul className={styles.valueList}>
      {values.map((value) => (
        <li key={value} className={styles.valueItem}>
          {value}
        </li>
      ))}
    </ul>
  );
}

function ReferencedList({ sources }: { sources: MessageWebSource[] }) {
  if (sources.length === 0) return null;
  return (
    <ul className={styles.sourceList}>
      {sources.map((source, index) => {
        const title = asString(source.title) ?? asString(source.url) ?? `Источник ${index + 1}`;
        const url = asString(source.url);
        const retrieved = asString(source.retrieved_at);
        return (
          <li key={source.id ?? `${url ?? title}-${index}`} className={styles.sourceItem}>
            <span className={styles.sourceTitle}>{title}</span>
            {url && (
              <a
                className={styles.sourceLink}
                href={url}
                target="_blank" rel="noreferrer noopener" title={url}
              >
                {url}
                <ExternalLink />
              </a>
            )}
            {retrieved && <span className={styles.sourceMeta}>получен {retrieved}</span>}
          </li>
        );
      })}
    </ul>
  );
}

/* ---- Block ----------------------------------------------------------------- */

export function MessageDiagnostics({ message }: { message: Message }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [copied, copy] = useCopyToClipboard();

  const model = useMemo(() => buildModel(message), [message]);
  const timings = message.timings;
  const webSources = message.web_sources ?? [];

  if (!hasMessageDiagnostics(message)) return null;

  const summary = collapsedLine(message, model);
  const route = timings?.route;
  const anchor = timings?.request_anchor;
  const research = timings?.research;
  const web = asRecord(timings?.web_search);
  const local = asRecord(timings?.local_context);
  const constraints = asStringArray(anchor?.constraints);
  const unknowns = asStringArray(anchor?.unknowns);
  const workingUsed = asStringArray(local?.working_titles);
  const workingDetails = Array.isArray(local?.working_source_details)
    ? (local?.working_source_details as unknown[]).map(asRecord).filter((item): item is Record<string, unknown> => item != null)
    : [];
  const workingCount = asNumber(local?.working_sources);
  const knowledgeUsed = asBoolean(local?.knowledge_used);
  const previousReferences = asNumber(local?.previous_references);
  const knowledgeStrategy = pickString(local, ['knowledge_strategy']);
  const contextTokens = asNumber(local?.context_tokens);
  const sourceTokens = asNumber(local?.source_tokens);
  const fullSourceCount = asNumber(local?.full_source_count);
  const repeatPurpose = pickString(web, ['repeat_purpose', 'repeat_reason', 'repeated_for', 'purpose']);
  const targetedRetrieval = pickBoolean(asRecord(research), [
    'targeted_retrieval',
    'additional_retrieval',
    'targeted_retrieval_used',
    'extra_retrieval',
  ]);

  const handleCopy = async () => {
    await copy(buildSummary(message, model));
    toast.success('Диагностика скопирована', 'Сводка отправлена в буфер обмена');
  };

  /* -- routing rows -- */
  const routingRows: ReactNode[] = [];
  if (route?.retrieval) {
    routingRows.push(
      <Row key="retrieval" label="Retrieval">
        <Badge tone={RETRIEVAL_TONES[route.retrieval] ?? 'neutral'} size="sm">
          {route.retrieval}
        </Badge>
      </Row>,
    );
  }
  if (route?.task_type) routingRows.push(<Row key="task" label="Тип задачи">{route.task_type}</Row>);
  if (route?.reasoning) routingRows.push(<Row key="reasoning" label="Reasoning">{route.reasoning}</Row>);
  if (route?.freshness_required != null) {
    routingRows.push(
      <Row key="freshness" label="Нужна свежесть">
        {yesNo(route.freshness_required)}
      </Row>,
    );
  }
  if (route?.verification != null) {
    routingRows.push(
      <Row key="verification" label="Верификация">
        {yesNo(route.verification)}
      </Row>,
    );
  }
  if (timings?.router_source) {
    routingRows.push(
      <Row key="router" label="Router">
        {ROUTER_LABELS[timings.router_source] ?? timings.router_source}
      </Row>,
    );
  }

  /* -- anchor rows -- */
  const anchorRows: ReactNode[] = [];
  if (anchor?.mode) {
    anchorRows.push(
      <Row key="mode" label="Режим">
        {ANCHOR_LABELS[anchor.mode] ?? anchor.mode}
      </Row>,
    );
  }
  if (asString(anchor?.subject)) anchorRows.push(<Row key="subject" label="Тема">{asString(anchor?.subject)}</Row>);
  if (asString(anchor?.task)) anchorRows.push(<Row key="task" label="Задача">{asString(anchor?.task)}</Row>);
  if (constraints.length > 0) {
    anchorRows.push(
      <Row key="constraints" label="Ограничения">
        <ValueList values={constraints} />
      </Row>,
    );
  }
  if (unknowns.length > 0) {
    anchorRows.push(
      <Row key="unknowns" label="Неизвестное">
        <ValueList values={unknowns} />
      </Row>,
    );
  }

  /* -- local context rows -- */
  const localRows: ReactNode[] = [];
  if (workingCount != null) localRows.push(<Row key="ws" label="Рабочих источников">{workingCount}</Row>);
  if (workingUsed.length > 0) {
    localRows.push(
      <Row key="used" label="Использованы">
        <ValueList values={workingUsed} />
      </Row>,
    );
  }
  if (knowledgeUsed != null) {
    localRows.push(
      <Row key="kb" label="База знаний">{yesNo(knowledgeUsed)}</Row>,
    );
  }
  if (previousReferences != null) {
    localRows.push(
      <Row key="prev" label="Ранее сохранённых ссылок">{previousReferences}</Row>,
    );
  }
  if (knowledgeStrategy != null) {
    localRows.push(
      <Row key="strategy" label="Стратегия контекста">
        {CONTEXT_STRATEGY_LABELS[knowledgeStrategy] ?? knowledgeStrategy}
      </Row>,
    );
  }
  if (contextTokens != null && sourceTokens != null) {
    // The difference between these two numbers is exactly what the answer did
    // not get to read.
    localRows.push(
      <Row key="tokens" label="Токенов отдано">{`${contextTokens} из ${sourceTokens}`}</Row>,
    );
  }
  if (fullSourceCount != null) {
    localRows.push(
      <Row key="full" label="Прочитано целиком">{`${fullSourceCount} ист.`}</Row>,
    );
  }

  /* -- web search rows -- */
  const webRows: ReactNode[] = [];
  if (model.searches != null) webRows.push(<Row key="searches" label="Поисковых запросов">{model.searches}</Row>);
  if (model.opened != null) webRows.push(<Row key="opened" label="Открытий страниц">{model.opened}</Row>);
  if (model.queries.length > 0) {
    webRows.push(
      <Row key="queries" label="Запросы">
        <ValueList values={model.queries} />
      </Row>,
    );
  }
  if (repeatPurpose != null) {
    webRows.push(<Row key="repeat" label="Повторный поиск">{repeatPurpose}</Row>);
  }

  /* -- research rows -- */
  const researchRows: ReactNode[] = [];
  if (model.isResearch) {
    researchRows.push(<Row key="requested" label="Запрошено">да</Row>);
    const reviewRounds = asNumber(asRecord(research)?.review_rounds);
    if (reviewRounds != null) researchRows.push(<Row key="rounds" label="Раундов проверки">{reviewRounds}</Row>);
    const revisions = asNumber(asRecord(research)?.revisions);
    if (revisions != null) researchRows.push(<Row key="revisions" label="Правок">{revisions}</Row>);
    const timedOut = asBoolean(asRecord(research)?.timed_out);
    if (timedOut != null) researchRows.push(<Row key="timeout" label="Таймаут">{yesNo(timedOut)}</Row>);
    if (targetedRetrieval != null) {
      researchRows.push(
        <Row key="targeted" label="Дополнительный поиск">{yesNo(targetedRetrieval)}</Row>,
      );
    }
    const skipped = asString(asRecord(research)?.skipped);
    if (skipped != null) researchRows.push(<Row key="skipped" label="Пропущено">{skipped}</Row>);
  }

  /* -- sources rows -- */
  const hasSourcesData =
    webSources.length > 0 || workingCount != null || workingUsed.length > 0 || workingDetails.length > 0;
  const sourcesRows: ReactNode[] = [];
  if (webSources.length > 0) {
    sourcesRows.push(
      <Row key="web-count" label="Referenced Sources">{webSources.length}</Row>,
    );
  }
  if (workingCount != null) sourcesRows.push(<Row key="working-count" label="Working Sources">{workingCount}</Row>);
  if (workingUsed.length > 0) {
    sourcesRows.push(
      <Row key="working-used" label="Использованы">
        <ValueList values={workingUsed} />
      </Row>,
    );
  }
  for (const [index, detail] of workingDetails.entries()) {
    const title = asString(detail.title) ?? asString(detail.url) ?? `Рабочий источник ${index + 1}`;
    const created = asBoolean(detail.created);
    const reused = asBoolean(detail.reused);
    const url = asString(detail.url) ?? pickString(detail, ['origin_url', 'source_url']);
    const provenance = pickString(detail, ['provenance', 'provenance_status']);
    const extraction = pickString(detail, ['extraction_status', 'extraction']);
    sourcesRows.push(
      <Row key={`working-detail-${index}`} label={title}>
        <span className={styles.workingMeta}>
          {created != null && <span>{created ? 'создан' : 'не создан'}</span>}
          {reused != null && <span>{reused ? 'переиспользован' : 'не переиспользован'}</span>}
          {url && (
            <a className={styles.sourceLink} href={url} target="_blank" rel="noreferrer noopener" title={url}>
              {url}
              <ExternalLink />
            </a>
          )}
          {provenance && <span>{provenance}</span>}
          {extraction && <span>{extraction}</span>}
        </span>
      </Row>,
    );
  }

  /* -- timing rows -- */
  const timingRows: ReactNode[] = [];
  for (const stage of model.stageTimings) {
    timingRows.push(
      <Row key={stage.label} label={stage.label}>
        <span className={styles.timingValue}>{stage.value} ms</span>
      </Row>,
    );
  }
  if (timings?.first_token_ms != null) {
    timingRows.push(
      <Row key="first_token" label="first_token_ms">
        <span className={styles.timingValue}>{timings.first_token_ms} ms</span>
      </Row>,
    );
  }
  if (timings?.total_ms != null) {
    timingRows.push(
      <Row key="total" label="total_ms">
        <span className={styles.timingValue}>{timings.total_ms} ms</span>
      </Row>,
    );
  }

  return (
    <div className={styles.diag}>
      <div className={styles.diagBar}>
        <button
          type="button" className={styles.diagToggle}
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <ChevronRight className={styles.diagChevron} data-open={open || undefined} aria-hidden />
          <span className={styles.diagTitle}>Диагностика</span>
          <span className={styles.diagSummary}>{summary}</span>
        </button>
        <span className={styles.diagActions}>
          <Tooltip label={copied ? 'Скопировано' : 'Скопировать сводку'}>
            <IconButton
              size="sm" label="Скопировать сводку диагностики" icon={copied ? <Check /> : <Copy />}
              onClick={() => void handleCopy()}
            />
          </Tooltip>
        </span>
      </div>

      {open && (
        <div className={styles.diagBody}>
          <Section title="Режим">
            <div className={styles.badges}>
              <Badge tone={model.isResearch ? 'danger' : 'neutral'} size="sm" dot>
                {model.isResearch ? 'RESEARCH' : 'AUTO'}
              </Badge>
            </div>
          </Section>

          {routingRows.length > 0 && <Section title="Маршрутизация">{routingRows}</Section>}

          {anchorRows.length > 0 && <Section title="Постановка запроса">{anchorRows}</Section>}

          {localRows.length > 0 && <Section title="Локальный контекст">{localRows}</Section>}

          {webRows.length > 0 && <Section title="Веб-поиск">{webRows}</Section>}

          {hasSourcesData && (
            <Section title="Источники">
              {sourcesRows}
              <ReferencedList sources={webSources} />
            </Section>
          )}

          {model.isResearch && researchRows.length > 0 && (
            <Section title="Research">{researchRows}</Section>
          )}

          {model.failures.length > 0 && (
            <Section title="Сбои">
              <div className={styles.badges}>
                {model.failures.map((failure) => (
                  <Badge key={failure.label} tone={failure.tone} size="sm" dot>
                    {failure.label}
                  </Badge>
                ))}
              </div>
            </Section>
          )}

          {timingRows.length > 0 && <Section title="Тайминги">{timingRows}</Section>}
        </div>
      )}
    </div>
  );
}
