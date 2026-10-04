import { useMemo, useState } from 'react';
import {
  KeyRound,
  Laptop,
  MoreHorizontal,
  Plus,
  Radio,
  ShieldOff,
  Trash2,
  Wifi,
} from 'lucide-react';
import { useActions } from '@/services';
import { useDevices, usePairingCodes, useServiceHealth } from '@/store';
import { useSession } from '@/session';
import { devicePresence, isPairingCodeActive, type Device } from '@/types';
import { formatRelativeTime } from '@/lib/format';
import { deviceSessionLabel } from '@/lib/deviceInfo';
import {
  Button,
  DataTable,
  EmptyState,
  IconButton,
  Menu,
  Metric,
  MetricStrip,
  Page,
  PageHeader,
  Panel,
  PanelBody,
  PanelHeader,
  useConfirm,
  useToast,
} from '@/components';
import type { Column } from '@/components';
import {
  DeviceIcon,
  DevicePresenceBadge,
  deviceKindLabel,
} from '@/components/Entities';
import { CodeCountdown, PairingCodeDialog } from './PairingCodeDialog';
import styles from './Devices.module.css';

export function DevicesPage() {
  const devices = useDevices();
  const codes = usePairingCodes();
  const services = useServiceHealth();
  const actions = useActions();
  const session = useSession();
  const confirm = useConfirm();
  const toast = useToast();

  const [pairingOpen, setPairingOpen] = useState(false);
  const activeDevices = devices.filter((device) => !device.revoked_at);
  const online = devices.filter((device) => devicePresence(device) === 'online');
  const liveCodes = useMemo(() => codes.filter((code) => isPairingCodeActive(code)), [codes]);

  const handleRevoke = async (device: Device) => {
    const ok = await confirm({
      title: `Отозвать «${device.name}»?`,
      description:
        'Устройство потеряет доступ к WristMind. Чтобы подключить его снова, потребуется новый код подключения.',
      confirmLabel: 'Отозвать устройство',
      confirmPhrase: 'отозвать',
      details: (
        <>
          <span>Тип: {deviceKindLabel(device.kind)}</span>
          {device.meta?.platform && <span>Платформа: {device.meta.platform}</span>}
          <span>Последняя активность: {formatRelativeTime(device.last_seen_at)}</span>
        </>
      ),
    });
    if (!ok) return;
    try {
      await actions.revokeDevice(device.id);
      toast.success('Устройство отозвано', device.name);
    } catch (error) {
      toast.error(
        'Не удалось отозвать устройство',
        error instanceof Error ? error.message : undefined,
      );
    }
  };

  const columns: Column<Device>[] = [
    {
      key: 'name',
      header: 'Устройство',
      mobilePrimary: true,
      width: '28%',
      render: (device) => (
        <div className={styles.deviceCell}>
          <DeviceIcon kind={device.kind} />
          <span className={styles.deviceText}>
            <span className={styles.deviceName}>
              {device.name}
              {device.id === session.deviceId && <span className={styles.currentTag}>эта панель</span>}
            </span>
            <span className={styles.devicePlatform}>
              {deviceSessionLabel(device.kind, device.user_agent) || device.meta?.platform || deviceKindLabel(device.kind)}
              {' · '}{device.id.slice(-6)}
            </span>
          </span>
        </div>
      ),
    },
    {
      key: 'kind',
      header: 'Тип',
      width: '120px',
      hideBelow: 'md',
      mobileLabel: 'Тип',
      render: (device) => <span className={styles.typeLabel}>{deviceKindLabel(device.kind)}</span>,
    },
    {
      key: 'status',
      header: 'Состояние',
      width: '140px',
      mobileLabel: 'Состояние',
      render: (device) => <DevicePresenceBadge presence={devicePresence(device)} />,
    },
    {
      key: 'ip',
      header: 'Последний IP',
      width: '150px',
      mobileLabel: 'Последний IP',
      render: (device) => (
        <span className={styles.mono}>{device.last_ip || device.enrolled_ip || device.meta?.ip_address || '—'}</span>
      ),
    },
    {
      key: 'lastSeen',
      header: 'Активность',
      width: '140px',
      align: 'right',
      mobileLabel: 'Активность',
      render: (device) => (
        <span className={styles.dim}>
          {devicePresence(device) === 'online'
            ? 'сейчас'
            : formatRelativeTime(device.last_seen_at)}
        </span>
      ),
    },
  ];

  return (
    <Page>
      <PageHeader
        title="Устройства" actions={
          <Button variant="primary" iconLeft={<Plus />} onClick={() => setPairingOpen(true)}>
            Подключить устройство
          </Button>
        }
      />

      <MetricStrip>
        <Metric label="С доступом" icon={<Radio />} value={activeDevices.length} meta="могут подключаться" />
        <Metric
          label="В сети" icon={<Wifi />}
          value={online.length}
          meta={online.length === activeDevices.length ? 'все на связи' : 'часть не в сети'}
        />
        <Metric
          label="Активных кодов" icon={<KeyRound />}
          value={liveCodes.length}
          meta={liveCodes.length > 0 ? 'действуют 10 минут' : 'нет активных кодов'}
        />
        <Metric
          label="Сервисы" icon={<ShieldOff />}
          value={`${services.filter((s) => s.status === 'operational').length}/${services.length}`}
          meta="в норме"
        />
      </MetricStrip>

      {liveCodes.length > 0 && (
        <Panel flush>
          <PanelHeader
            title="Активные коды подключения" icon={<KeyRound />}
          />
          <ul className={styles.codeList}>
            {liveCodes.map((code) => (
              <li key={code.code} className={styles.codeRow}>
                <span className={styles.codeValue}>{code.code}</span>
                <span className={styles.codeMeta}>
                  {code.target_kind ? deviceKindLabel(code.target_kind) : 'Любое устройство'}
                  {' · выпущен '}
                  {formatRelativeTime(code.created_at)}
                </span>
                <CodeCountdown expiresAt={code.expires_at} className={styles.codeCountdown} />
                <Button
                  size="sm" variant="ghost" iconLeft={<Trash2 />}
                  onClick={() => void actions.revokePairingCode(code.code)}
                >
                  Отозвать
                </Button>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel flush>
        <PanelHeader
          title="Устройства с доступом" actions={
            <Button
              size="sm" variant="secondary" iconLeft={<Plus />}
              onClick={() => setPairingOpen(true)}
            >
              Новый код
            </Button>
          }
        />
        <PanelBody>
          <DataTable
            columns={columns}
            rows={activeDevices}
            rowKey={(device) => device.id}
            emptyState={
              <EmptyState
                icon={<Laptop />}
                title="Устройств с доступом нет" description="Выпустите код подключения и введите его в приложении на телефоне или часах." action={
                  <Button variant="primary" iconLeft={<Plus />} onClick={() => setPairingOpen(true)}>
                    Подключить устройство
                  </Button>
                }
              />
            }
            rowActions={(device) => {
              const isCurrent = device.id === session.deviceId;
              return (
                <Menu
                  align="end" width={236}
                  entries={[
                    {
                      type: 'item',
                      id: 'revoke',
                      label: 'Отозвать доступ',
                      icon: <ShieldOff />,
                      danger: true,
                      disabled: isCurrent,
                      description: isCurrent ? 'Нельзя отозвать текущую панель' : undefined,
                      onSelect: () => handleRevoke(device),
                    },
                  ]}
                  trigger={
                    <IconButton size="sm" label="Действия с устройством" icon={<MoreHorizontal />} />
                  }
                />
              );
            }}
          />
        </PanelBody>
      </Panel>

      <PairingCodeDialog open={pairingOpen} onClose={() => setPairingOpen(false)} />
    </Page>
  );
}
