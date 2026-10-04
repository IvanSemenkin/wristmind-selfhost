import type { IsoDateTime, JobStatus } from './common';

/* =============================================================================
   Knowledge base
   ========================================================================== */

/** How the document is turned into text. */
export type ProcessingMode = 'OCR' | 'VISION';

export const PROCESSING_MODES: ProcessingMode[] = ['OCR', 'VISION'];

export const PROCESSING_MODE_LABELS: Record<ProcessingMode, string> = {
  OCR: 'OCR',
  VISION: 'Vision',
};

/** MIME types accepted by the upload endpoint. */
export const ACCEPTED_MEDIA_TYPES = [
  'application/pdf',
  'image/jpeg',
  'image/jpg',
  'image/png',
  'image/webp',
] as const;

export const ACCEPT_ATTRIBUTE = '.pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp';

export type SourceKind = 'pdf' | 'image';

export function sourceKind(mediaType: string, filename = ''): SourceKind {
  if (mediaType.startsWith('image/')) return 'image';
  if (/\.(jpe?g|png|webp)$/i.test(filename)) return 'image';
  return 'pdf';
}

export interface KnowledgeSource {
  id: string;
  mode_id: string;
  title: string;
  filename: string;
  /** MIME type of the uploaded file. */
  media_type: string;
  processing_mode: ProcessingMode;
  status: JobStatus;
  page_count: number;
  chunk_count: number;
  token_count: number;
  error: string | null;
  created_at: IsoDateTime;
  /** Optional: falls back to `created_at` when the backend omits it. */
  updated_at?: IsoDateTime;
  /**
   * Optional processing telemetry. Present only while a background job runs;
   * the console falls back to the status label when it is absent.
   */
  progress?: number;
  stage?: string | null;
}

export interface SourcePage {
  index: number;
  text: string;
  chars: number;
  /** Vision-analyzed pages report a confidence score. */
  confidence?: number;
}

export interface SourceChunk {
  id: string;
  index: number;
  page: number;
  text: string;
  tokens: number;
}

/** Extracted content, loaded on demand when a source is opened. */
export interface SourceContent {
  source_id: string;
  pages: SourcePage[];
  chunks: SourceChunk[];
}

export interface SourceUploadInput {
  mode_id: string;
  title: string;
  file: File | { name: string; size: number; type: string };
  processing_mode: ProcessingMode;
}

/**
 * Upload returns a background job rather than a finished document: the console
 * shows `uploading` → `processing` → `ready | error` and refreshes from the
 * service subscription, without reloading the page.
 */
export interface SourceUploadResult {
  source: KnowledgeSource;
  job_id: string;
}
