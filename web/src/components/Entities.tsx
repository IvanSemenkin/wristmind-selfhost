import { Link } from '@/app/router';
import { Cloud, Cpu, Monitor, Server, Smartphone, Watch } from 'lucide-react';
import type {
  DeviceKind,
  DevicePresence,
  JobStatus,
  Model,
  ModelCapability,
  ServiceStatus,
} from '@/types';
import { DEVICE_KIND_LABELS, MODEL_CAPABILITY_LABELS } from '@/types';
import { cn } from '@/lib/cn';
import { Badge } from '@/components';
import type { Tone } from '@/components';
import styles from './Entities.module.css';

/* -------------------------------------------------------------------------- */
/* Modes                                                                      */
/* -------------------------------------------------------------------------- */

export function ModeDot({
  color,
  size = 'md',
  className,
}: {
  color?: string | null;
  /** Kept for API compatibility; mode icons are intentionally not shown. */
  icon?: string | null;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}) {
  return (
    <span
      className={cn(styles.modeDot, className)}
      data-size={size}
      data-mode-color={color ?? undefined}
      aria-hidden
    />
  );
}

export function ModeBadge({
  modeId,
  color,
  icon,
  name,
  size = 'md',
  linkTo = true,
}: {
  modeId: string | null;
  color?: string | null;
  icon?: string | null;
  name: string;
  size?: 'sm' | 'md';
  linkTo?: boolean;
}) {
  const content = (
    <>
      <ModeDot color={color} icon={icon} size={size === 'sm' ? 'sm' : 'md'} />
      <span className={styles.modeBadgeName}>{name}</span>
    </>
  );

  if (!linkTo || !modeId) {
    return (
      <span className={styles.modeBadge} data-size={size} data-mode-color={color ?? undefined}>
        {content}
      </span>
    );
  }

  return (
    <Link
      to={`/modes/${modeId}`}
      className={styles.modeBadge}
      data-size={size}
      data-mode-color={color ?? undefined}
      data-interactive
    >
      {content}
    </Link>
  );
}

export function QuickChatBadge({ size = 'md' }: { size?: 'sm' | 'md' }) {
  return (
    <span className={styles.quickBadge} data-size={size}>
      <ModeDot size={size === 'sm' ? 'sm' : 'md'} />
      <span>Быстрый чат</span>
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Models                                                                     */
/* -------------------------------------------------------------------------- */

export const capabilityLabel = (capability: ModelCapability): string =>
  MODEL_CAPABILITY_LABELS[capability];

export function ModelIcon({ model, className }: { model?: Model; className?: string }) {
  const local = model?.capabilities.includes('local');
  return (
    <span className={cn(styles.modelIcon, className)} data-local={local || undefined}>
      {local ? <Cpu /> : <Cloud />}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Knowledge sources                                                          */
/* -------------------------------------------------------------------------- */

export const SOURCE_STATUS_META: Record<JobStatus, { label: string; tone: Tone }> = {
  uploading: { label: 'Загрузка', tone: 'neutral' },
  processing: { label: 'Обработка', tone: 'info' },
  ready: { label: 'Готово', tone: 'success' },
  error: { label: 'Ошибка', tone: 'danger' },
};

export function SourceStatusBadge({ status }: { status: JobStatus }) {
  const meta = SOURCE_STATUS_META[status];
  return (
    <Badge tone={meta.tone} dot size="sm">
      {meta.label}
    </Badge>
  );
}

/* -------------------------------------------------------------------------- */
/* Devices & services                                                         */
/* -------------------------------------------------------------------------- */

export function DeviceIcon({ kind, className }: { kind: DeviceKind; className?: string }) {
  const Icon = kind === 'PHONE' ? Smartphone : kind === 'WATCH' ? Watch : kind === 'TELEGRAM' ? Server : Monitor;
  return (
    <span className={cn(styles.deviceIcon, className)} data-type={kind.toLowerCase()}>
      <Icon />
    </span>
  );
}

/** Presence is derived from timestamps, not stored on the device record. */
export const DEVICE_PRESENCE_META: Record<DevicePresence, { label: string; tone: Tone }> = {
  online: { label: 'В сети', tone: 'success' },
  idle: { label: 'Неактивно', tone: 'warning' },
  revoked: { label: 'Отозвано', tone: 'neutral' },
};

export function DevicePresenceBadge({ presence }: { presence: DevicePresence }) {
  const meta = DEVICE_PRESENCE_META[presence];
  return (
    <Badge tone={meta.tone} dot size="sm">
      {meta.label}
    </Badge>
  );
}

export const deviceKindLabel = (kind: DeviceKind): string => DEVICE_KIND_LABELS[kind];

export const SERVICE_STATUS_META: Record<ServiceStatus, { label: string; tone: Tone }> = {
  operational: { label: 'Работает', tone: 'success' },
  degraded: { label: 'Деградация', tone: 'warning' },
  down: { label: 'Недоступно', tone: 'danger' },
};

export function ServiceStatusBadge({ status }: { status: ServiceStatus }) {
  const meta = SERVICE_STATUS_META[status];
  return (
    <Badge tone={meta.tone} dot size="sm">
      {meta.label}
    </Badge>
  );
}
