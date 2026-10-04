import { useEffect, useState } from 'react';
import { Link } from '@/app/router';
import {
  ArrowUpRight,
  BookOpen,
  CheckCircle2,
  Cpu,
  Layers,
  MessagesSquare,
  Plus,
  Radio,
  ShieldAlert,
  Upload,
  Watch,
} from 'lucide-react';
import {
  useApiPath,
  useDerivedStats,
  useDevices,
  useModes,
  useModels,
  useServiceHealth,
  useSources,
  useStoreStatus,
} from '@/store';
import { useStore } from '@/services';
import { useSession } from '@/session';
import { formatCompact, formatNumber } from '@/lib/format';
import {
  ActivityChart,
  Button,
  EmptyState,
  Metric,
  MetricStrip,
  Page,
  PageHeader,
  Panel,
  PanelBody,
  PanelHeader,
  RankedBars,
  Sparkline,
} from '@/components';
import { ServiceStatusBadge, deviceKindLabel } from '@/components/Entities';
import { useQuickActions } from '@/app/QuickActions';
import styles from './Overview.module.css';

export function OverviewPage() {
  const modes = useModes();
  const sources = useSources();
  const devices = useDevices();
  const services = useServiceHealth();
  const apiPath = useApiPath();
  const models = useModels();
  const stats = useDerivedStats();
  const quick = useQuickActions();
  const session = useSession();
  const store = useStore();
  const { status } = useStoreStatus();
  const [refreshFailed, setRefreshFailed] = useState(false);

  useEffect(() => {
    let mounted = true;
    const refresh = () => {
      if (status !== 'ready' || document.visibilityState !== 'visible') return;
      void store.refreshOverview().then(
        () => { if (mounted) setRefreshFailed(false); },
        () => { if (mounted) setRefreshFailed(true); },
      );
    };
    refresh();
    const interval = window.setInterval(refresh, 60_000);
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      mounted = false;
      window.clearInterval(interval);
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [status, store]);

  const colorFor = (modeId: string) => {
    const mode = modes.find((m) => m.id === modeId);
    if (!mode) return undefined;
    return `var(--c-${mode.color})`;
  };

  const reqTrend =
    stats.requestsYesterday > 0
      ? ((stats.requestsToday - stats.requestsYesterday) / stats.requestsYesterday) * 100
      : 0;

  const usageItems = stats.usage
    .map((entry) => {
      const mode = modes.find((m) => m.id === entry.mode_id);
      return {
        id: entry.mode_id,
        label: mode?.name ?? 'Удалённый режим',
        value: entry.requests,
        display: `${formatCompact(entry.requests)} запр.`,
        meta: entry.tokens > 0 ? `${formatCompact(entry.tokens)} токенов` : 'за 14 дней',
        color: mode ? colorFor(mode.id) : undefined,
      };
    })
    .sort((a, b) => b.value - a.value);

  return (
    <Page>
      <PageHeader
        title="Обзор" actions={
          <>
            <Button
              variant="secondary" iconLeft={<Upload />}
              onClick={() => quick.uploadSource(null)}
            >
              Загрузить источник
            </Button>
            <Button variant="primary" iconLeft={<Plus />} onClick={() => quick.newChat(null)}>
              Новый чат
            </Button>
          </>
        }
      />

      {refreshFailed && (
        <p className={styles.refreshWarning} role="status">Не удалось обновить данные обзора. Повторим при возвращении на страницу или через минуту.</p>
      )}

      <MetricStrip>
        <Metric
          label="Запросы к ИИ" icon={<Cpu />}
          value={formatNumber(stats.totalAiRequests)}
          meta={
            <>
              <span>Сегодня {formatNumber(stats.requestsToday)} · вчера {formatNumber(stats.requestsYesterday)}</span>
              {stats.requestsYesterday > 0 && (
                <span className={styles.trend} data-up={reqTrend >= 0 || undefined}>
                  {reqTrend >= 0 ? '+' : ''}{reqTrend.toFixed(1)}%
                </span>
              )}
              <span className={styles.metricSpark}>
                <Sparkline
                  values={stats.activity.map((a) => a.requests)}
                  width={54}
                  height={16}
                  tone={reqTrend >= 0 ? 'success' : 'danger'}
                />
              </span>
            </>
          }
        />
        <Metric
          label="Ошибки" icon={<ShieldAlert />}
          value={`${stats.errorRateToday.toFixed(1)}%`}
          meta={`${formatNumber(stats.activity.at(-1)?.errors ?? 0)} с ошибкой сегодня`}
        />
        <Metric
          label="Режимы" icon={<Layers />}
          value={stats.modeCount}
          meta={
            <>
              <Watch />
              {stats.watchModeCount} на часах
            </>
          }
        />
        <Metric
          label="Чаты" icon={<MessagesSquare />}
          value={stats.chatCount}
          meta="активных диалогов"
        />
        <Metric
          label="База знаний" icon={<BookOpen />}
          value={stats.readySources.length}
          meta={
            stats.processing.length > 0 ? (
              <span className={styles.processingHint}>{stats.processing.length} в обработке</span>
            ) : (
              `${formatCompact(stats.totalTokens)} токенов`
            )
          }
        />
        <Metric
          label="Устройства" icon={<Radio />}
          value={`${stats.activeDeviceCount}/${stats.deviceCount}`}
          meta="с действующим доступом / всего"
        />
      </MetricStrip>

      <div className={styles.twoCol}>
        <Panel>
          <PanelHeader
            title="Активность помощника"
          />
          <PanelBody>
            <ActivityChart points={stats.activity} />
          </PanelBody>
        </Panel>

        <Panel flush>
          <PanelHeader
            title="Состояние системы" actions={
              <Link to="/devices" className={styles.headerLink}>
                Устройства <ArrowUpRight />
              </Link>
            }
          />
          {apiPath === 'fallback' && (
            <p className={styles.modeNote} data-mode="fallback">
              <span className={styles.modeNoteDot} aria-hidden />
              Резервный режим: основной сервер недоступен, отвечает внешний сервер.
            </p>
          )}
          {apiPath === 'none' && (
            <p className={styles.modeNote} data-mode="none">
              <span className={styles.modeNoteDot} aria-hidden />
              Основной и резервный серверы не отвечают.
            </p>
          )}
          <ul className={styles.serviceList}>
            {services.map((service) => (
              <li key={service.id} className={styles.serviceRow}>
                <div className={styles.serviceMain}>
                  <span className={styles.serviceTitle}>{service.label}</span>
                  <span className={styles.serviceDetail}>{service.detail}</span>
                </div>
                <div className={styles.serviceSide}>
                  <ServiceStatusBadge status={service.status} />
                  <span className={styles.serviceLatency}>
                    {service.latency_ms != null ? `${service.latency_ms} мс` : '—'}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <Panel>
        <PanelHeader title="Нагрузка по режимам" />
        <PanelBody>
          {usageItems.length > 0 ? (
            <RankedBars items={usageItems} />
          ) : (
            <EmptyState compact title="Нет данных об использовании" />
          )}
        </PanelBody>
      </Panel>

      <Panel tone="inset">
        <PanelBody>
          <div className={styles.systemFootnote}>
            <CheckCircle2 />
            <span>
              Панель подключена к WristMind API: {models.length} моделей, {sources.length}{' '}
              источников и {devices.length} устройств. Устройство панели:{' '}
              {deviceKindLabel('WEB')} · {session.deviceId}.
            </span>
          </div>
        </PanelBody>
      </Panel>
    </Page>
  );
}
