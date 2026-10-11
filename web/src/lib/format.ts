const numberFormat = new Intl.NumberFormat('ru-RU');
const compactFormat = new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 });
const dateFormat = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' });
const dateYearFormat = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' });
const timeFormat = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' });
const dateTimeFormat = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
});

export const formatNumber = (value: number): string => numberFormat.format(value);

export const formatCompact = (value: number): string => compactFormat.format(value);

export const formatDateTime = (iso: string): string => dateTimeFormat.format(new Date(iso));

export const formatTime = (iso: string): string => timeFormat.format(new Date(iso));

export const formatDate = (iso: string): string => {
  const date = new Date(iso);
  return date.getFullYear() === new Date().getFullYear()
    ? dateFormat.format(date)
    : dateYearFormat.format(date);
};

/** Compact, human "time ago" label used in lists and tables. */
export function formatRelativeTime(iso: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime();
  const diff = Math.max(0, now - then);
  const seconds = Math.floor(diff / 1000);
  if (seconds < 45) return 'только что';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} ${plural(minutes, 'минуту', 'минуты', 'минут')} назад`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ${plural(hours, 'час', 'часа', 'часов')} назад`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'вчера';
  if (days < 7) return `${days} ${plural(days, 'день', 'дня', 'дней')} назад`;
  return formatDate(iso);
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} мс`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} с`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} мин ${Math.round(seconds % 60)} с`;
}

export function formatBytes(bytes: number): string {
  if (bytes <= 0) return '0 Б';
  const units = ['Б', 'КБ', 'МБ', 'ГБ'];
  const exponent = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const value = bytes / 1024 ** exponent;
  const digits = value < 10 && exponent > 0 ? 1 : 0;
  return `${value.toFixed(digits)} ${units[exponent]}`;
}

/** 10:00 → "10:00", used for the pairing-code countdown. */
export function formatCountdown(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

/** Russian plural agreement: plural(2, 'файл', 'файла', 'файлов') → 'файла'. */
export function plural(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}
