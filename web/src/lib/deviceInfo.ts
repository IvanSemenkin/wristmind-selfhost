/** Human-readable session label from the user agent saved by the API. */
export function deviceSessionLabel(kind: string, userAgent: string | null | undefined): string {
  if (kind === 'WATCH') return 'Wear OS';
  const agent = userAgent ?? '';
  const system = /Android/i.test(agent) ? 'Android'
    : /iPhone|iPad|iPod/i.test(agent) ? 'iOS'
      : /Windows/i.test(agent) ? 'Windows'
        : /Macintosh|Mac OS X/i.test(agent) ? 'macOS'
          : /Linux/i.test(agent) ? 'Linux' : '';
  if (kind === 'PHONE') return system || 'Телефон';
  if (kind !== 'WEB') return '';
  const browser = /Edg\//i.test(agent) ? 'Edge'
    : /Firefox\//i.test(agent) ? 'Firefox'
      : /Chrome\//i.test(agent) ? 'Chrome'
        : /Safari\//i.test(agent) ? 'Safari' : 'Браузер';
  return [browser, system].filter(Boolean).join(' · ');
}
