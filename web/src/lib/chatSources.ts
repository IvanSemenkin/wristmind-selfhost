import type {
  ChatReferencedSource,
  ChatSources,
  ChatWorkingSource,
  MessageWebSource,
} from '../types/chat';
import { domainFromUrl } from './webSources.ts';

/* =============================================================================
   Chat sources — pure presentation logic.

   This module is deliberately framework-free and runs unchanged under plain
   Node (`node --test --experimental-strip-types`). It therefore uses a relative
   runtime import for `domainFromUrl` and type-only imports everywhere else, so
   nothing here needs a bundler or a path alias at runtime.

   Vocabulary (the product keeps these two worlds apart):
     • Working Sources  — material the backend extracted for this one chat;
     • Referenced Sources — public-web pages cited while answering in this chat.
   ========================================================================== */

export type ChatSourceKind = 'working' | 'referenced';
export type ChatSourceFilter = 'all' | 'working' | 'referenced';

/** One renderable card, normalised across both source shapes. */
export interface ChatSourceCard {
  /** Stable React key, unique inside a merged list. */
  key: string;
  kind: ChatSourceKind;
  id: string;
  title: string;
  /** `origin_url` for a working source, `url` for a referenced one. */
  url: string | null;
  domain: string | null;
  /** The origin page title a working source was taken from, when present. */
  originTitle: string | null;
  snippet: string | null;
  status: string | null;
  createdAt: string | null;
  retrievedAt: string | null;
  /** The answer a referenced entry belongs to, when the backend reports it. */
  messageId: string | null;
}

/** The slice of `Message` this module needs; keeps the tests fixture-free. */
export interface MessageSourceContext {
  id?: string;
  web_sources?: Pick<MessageWebSource, 'id' | 'title' | 'url' | 'retrieved_at' | 'snippet'>[];
  timings?: { local_context?: { working_titles?: string[] } | null } | null;
}

/* -------------------------------------------------------------------------- */
/* Normalisation                                                              */
/* -------------------------------------------------------------------------- */

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

/**
 * Canonical key used for URL comparison: scheme + lowercase host + path without
 * a trailing slash + query. The fragment is dropped. Anything unparseable is
 * compared case-insensitively after trimming a trailing slash.
 */
export function normalizeSourceUrl(raw: unknown): string {
  const value = text(raw);
  if (!value) return '';
  try {
    const url = new URL(value);
    const path = url.pathname.replace(/\/+$/, '');
    return `${url.protocol}//${url.hostname.toLowerCase()}${path}${url.search}`;
  } catch {
    return value.replace(/\/+$/, '').toLowerCase();
  }
}

function normalizeTitleKey(value: unknown): string {
  return text(value).toLowerCase().replace(/\s+/g, ' ');
}

function normalizeWorkingList(value: unknown): ChatWorkingSource[] {
  if (!Array.isArray(value)) return [];
  const list: ChatWorkingSource[] = [];
  value.forEach((raw, index) => {
    if (!raw || typeof raw !== 'object') return;
    const record = raw as Record<string, unknown>;
    const originUrl = text(record.origin_url);
    const title = text(record.title) || text(record.origin_title) || originUrl;
    if (!title && !originUrl) return;
    list.push({
      id: text(record.id) || `working-${index}`,
      title: title || originUrl,
      origin_url: originUrl || null,
      origin_title: text(record.origin_title) || null,
      status: text(record.status) || null,
      created_at: text(record.created_at) || null,
    });
  });
  return list;
}

function normalizeReferencedList(value: unknown): ChatReferencedSource[] {
  if (!Array.isArray(value)) return [];
  const list: ChatReferencedSource[] = [];
  value.forEach((raw, index) => {
    if (!raw || typeof raw !== 'object') return;
    const record = raw as Record<string, unknown>;
    const url = text(record.url);
    if (!url) return;
    list.push({
      id: text(record.id) || `referenced-${index}`,
      title: text(record.title) || domainFromUrl(url) || url,
      url,
      snippet: text(record.snippet) || null,
      retrieved_at: text(record.retrieved_at) || null,
      message_id: text(record.message_id) || null,
    });
  });
  return list;
}

/** Tolerant mapper for the raw `GET /v1/chats/{id}/sources` payload. */
export function normalizeChatSources(value: unknown): ChatSources {
  const record = value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
  return {
    working: normalizeWorkingList(record.working),
    referenced: normalizeReferencedList(record.referenced),
  };
}

/* -------------------------------------------------------------------------- */
/* Cards                                                                      */
/* -------------------------------------------------------------------------- */

function workingCard(source: ChatWorkingSource): ChatSourceCard {
  const url = source.origin_url || null;
  const urlKey = normalizeSourceUrl(url);
  return {
    key: `working:${urlKey || source.id}`,
    kind: 'working',
    id: source.id,
    title: source.title,
    url,
    domain: url ? domainFromUrl(url) || null : null,
    originTitle: source.origin_title,
    snippet: null,
    status: source.status,
    createdAt: source.created_at,
    retrievedAt: null,
    messageId: null,
  };
}

function referencedCard(source: ChatReferencedSource): ChatSourceCard {
  const domain = domainFromUrl(source.url) || null;
  return {
    key: `referenced:${normalizeSourceUrl(source.url) || source.id}`,
    kind: 'referenced',
    id: source.id,
    title: source.title || domain || source.url,
    url: source.url,
    domain,
    originTitle: null,
    snippet: source.snippet,
    status: null,
    createdAt: null,
    retrievedAt: source.retrieved_at,
    messageId: source.message_id,
  };
}

/**
 * Merge working and referenced cards into one unique list.
 *
 * Rules:
 *   • a Working Source wins over a Referenced one with the same URL;
 *   • working sources without an origin URL are deduplicated by id;
 *   • referenced sources are deduplicated by URL.
 */
export function mergeChatSourceCards(
  working: ChatSourceCard[],
  referenced: ChatSourceCard[],
): ChatSourceCard[] {
  const seenWorking = new Set<string>();
  const workingUrls = new Set<string>();
  const uniqueWorking: ChatSourceCard[] = [];

  for (const card of working) {
    const urlKey = normalizeSourceUrl(card.url);
    const key = urlKey || card.key;
    if (seenWorking.has(key)) continue;
    seenWorking.add(key);
    if (urlKey) workingUrls.add(urlKey);
    uniqueWorking.push(card);
  }

  const seenReferenced = new Set<string>();
  const uniqueReferenced: ChatSourceCard[] = [];
  for (const card of referenced) {
    const urlKey = normalizeSourceUrl(card.url);
    if (!urlKey || workingUrls.has(urlKey) || seenReferenced.has(urlKey)) continue;
    seenReferenced.add(urlKey);
    uniqueReferenced.push(card);
  }

  return [...uniqueWorking, ...uniqueReferenced];
}

/** Every unique source of a chat: working materials first, then the web. */
export function chatSourceCards(sources: ChatSources | null | undefined): ChatSourceCard[] {
  if (!sources) return [];
  return mergeChatSourceCards(
    (sources.working ?? []).map(workingCard),
    (sources.referenced ?? []).map(referencedCard),
  );
}

/**
 * The sources tied to one answer: its own `web_sources` plus the chat Working
 * Sources whose titles the answer reports in `local_context.working_titles`.
 *
 * Old messages may name a working source the chat index no longer returns; a
 * title-only card is produced so the answer's panel stays honest instead of
 * silently dropping it.
 */
export function messageSourceCards(
  message: MessageSourceContext | null | undefined,
  sources: ChatSources | null | undefined,
): ChatSourceCard[] {
  if (!message) return [];

  const titles = (message.timings?.local_context?.working_titles ?? [])
    .map((title) => text(title))
    .filter(Boolean);

  const wanted = new Set(titles.map(normalizeTitleKey));
  const used = new Set<string>();
  const working: ChatSourceCard[] = [];

  for (const card of (sources?.working ?? []).map(workingCard)) {
    const key = normalizeTitleKey(card.title);
    const usedWebUrl = (message.web_sources ?? []).some(
      (source) => normalizeSourceUrl(source?.url) === normalizeSourceUrl(card.url) && !!card.url,
    );
    if ((!key || !wanted.has(key)) && !usedWebUrl) continue;
    if (key && used.has(key)) continue;
    if (key) used.add(key);
    working.push(card);
  }

  titles.forEach((title, index) => {
    const key = normalizeTitleKey(title);
    if (!key || used.has(key)) return;
    used.add(key);
    working.push({
      key: `working:title:${key}:${index}`,
      kind: 'working',
      id: `working-title-${index}`,
      title,
      url: null,
      domain: null,
      originTitle: null,
      snippet: null,
      status: null,
      createdAt: null,
      retrievedAt: null,
      messageId: message.id ?? null,
    });
  });

  const referenced: ChatSourceCard[] = [];
  (message.web_sources ?? []).forEach((source, index) => {
    const url = text(source?.url);
    if (!url) return;
    const domain = domainFromUrl(url) || null;
    const title = text(source?.title) || domain || url;
    referenced.push({
      key: `referenced:${normalizeSourceUrl(url)}:${index}`,
      kind: 'referenced',
      id: text(source?.id) || `msg-web-${index}`,
      title,
      url,
      domain,
      originTitle: null,
      snippet: text(source?.snippet) || null,
      status: null,
      createdAt: null,
      retrievedAt: text(source?.retrieved_at) || null,
      messageId: message.id ?? null,
    });
  });

  return mergeChatSourceCards(working, referenced);
}

/* -------------------------------------------------------------------------- */
/* Filters & presentation                                                     */
/* -------------------------------------------------------------------------- */

export function filterChatSourceCards(
  cards: ChatSourceCard[],
  filter: ChatSourceFilter,
): ChatSourceCard[] {
  if (filter === 'working') return cards.filter((card) => card.kind === 'working');
  if (filter === 'referenced') return cards.filter((card) => card.kind === 'referenced');
  return cards;
}

export function countChatSourceKinds(cards: ChatSourceCard[]): {
  all: number;
  working: number;
  referenced: number;
} {
  let working = 0;
  let referenced = 0;
  for (const card of cards) {
    if (card.kind === 'working') working += 1;
    else referenced += 1;
  }
  return { all: cards.length, working, referenced };
}

/**
 * A letter monogram derived from the source's domain (falling back to its
 * title). The console never calls a third-party favicon endpoint.
 */
export function sourceMonogram(card: Pick<ChatSourceCard, 'domain' | 'title'>): string {
  const host = text(card.domain);
  const label = host.split('.').find((part) => part.length > 0) ?? text(card.title);
  const first = label.trim()[0] ?? '?';
  return first.toUpperCase();
}
