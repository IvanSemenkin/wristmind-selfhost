import { useEffect, useState } from 'react';
import { Link } from '@/app/router';
import {
  AlertTriangle,
  KeyRound,
  Monitor,
  Moon,
  Save,
  Sun,
} from 'lucide-react';
import { useActions } from '@/services';
import { useModels, usePairingCodes, useSettings } from '@/store';
import { useSession } from '@/session';
import { isPairingCodeActive } from '@/types';
import { formatCompact, formatRelativeTime } from '@/lib/format';
import {
  Badge,
  Button,
  Field,
  Page,
  PageHeader,
  Panel,
  PanelBody,
  PanelHeader,
  SegmentedControl,
  Select,
  Switch,
  useConfirm,
  useToast,
} from '@/components';
import { useTheme, type Theme } from '@/app/ThemeProvider';
import styles from './Settings.module.css';

const HISTORY_OPTIONS = [4, 6, 8, 12, 16, 24, 32];
const RETENTION_OPTIONS = [
  { value: '30', label: '30 дней' },
  { value: '90', label: '90 дней' },
  { value: '180', label: '180 дней' },
  { value: '365', label: '1 год' },
  { value: '0', label: 'Бессрочно' },
];

export function SettingsPage() {
  const settings = useSettings();
  const models = useModels();
  const codes = usePairingCodes();
  const actions = useActions();
  const confirm = useConfirm();
  const toast = useToast();
  const session = useSession();
  const { theme, setTheme } = useTheme();

  const [developerMode, setDeveloperMode] = useState(false);
  const [historyLimit, setHistoryLimit] = useState(12);
  const [defaultModelId, setDefaultModelId] = useState('');
  const [streamResponses, setStreamResponses] = useState(true);
  const [retention, setRetention] = useState('90');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!settings) return;
    setDeveloperMode(settings.developer_mode);
    setHistoryLimit(settings.history_limit);
    setDefaultModelId(settings.default_model_id);
    setStreamResponses(settings.stream_responses);
    setRetention(String(settings.retention_days));
  }, [settings]);

  if (!settings) {
    return (
      <Page>
        <PageHeader title="Настройки" />
      </Page>
    );
  }

  const dirty =
    developerMode !== settings.developer_mode ||
    historyLimit !== settings.history_limit ||
    defaultModelId !== settings.default_model_id ||
    streamResponses !== settings.stream_responses ||
    Number(retention) !== settings.retention_days;

  const liveCodes = codes.filter((code) => isPairingCodeActive(code));

  const save = async () => {
    setSaving(true);
    try {
      await actions.updateSettings({
        developer_mode: developerMode,
        history_limit: historyLimit,
        default_model_id: defaultModelId,
        stream_responses: streamResponses,
        retention_days: Number(retention),
      });
      toast.success('Настройки сохранены');
    } catch {
      toast.error('Не удалось сохранить настройки');
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    setDeveloperMode(settings.developer_mode);
    setHistoryLimit(settings.history_limit);
    setDefaultModelId(settings.default_model_id);
    setStreamResponses(settings.stream_responses);
    setRetention(String(settings.retention_days));
  };

  const disconnectPanel = async () => {
    const ok = await confirm({
      title: 'Отключить эту веб-панель?',
      description:
        'Текущая сессия будет завершена, доступ к панели нужно будет восстановить новым кодом подключения. Чаты, режимы и базы знаний сохранятся.',
      confirmLabel: 'Отключить панель',
      confirmPhrase: 'отключить',
      details: (
        <>
          <span>Устройство: {session.deviceId}</span>
          <span>Роль: администратор</span>
        </>
      ),
    });
    if (!ok) return;
    try {
      const response = await fetch(`${session.baseUrl.replace(/\/+$/, '')}/v1/devices/self`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${session.token}` },
      });
      if (!response.ok) throw new Error();
      window.localStorage.removeItem('wristmind.web.session');
      window.location.assign('/main');
    } catch {
      toast.error('Не удалось отключить панель. Попробуйте ещё раз.');
    }
  };

  return (
    <Page>
      <PageHeader
        title="Настройки" actions={
          liveCodes.length > 0 ? (
            <Badge tone="accent" size="md" dot>
              {liveCodes.length} активный код
            </Badge>
          ) : undefined
        }
      />

      <div className={styles.grid}>
        <div className={styles.main}>
          <Panel>
            <PanelHeader
              title="Контекст диалога"
            />
            <PanelBody>
              <div className={styles.stack}>
                <div className={styles.contextRow}>
                  <input
                    type="range" className={styles.range}
                    min={0}
                    max={HISTORY_OPTIONS.length - 1}
                    step={1}
                    value={Math.max(0, HISTORY_OPTIONS.indexOf(historyLimit))}
                    onChange={(e) =>
                      setHistoryLimit(HISTORY_OPTIONS[Number(e.target.value)] ?? HISTORY_OPTIONS[0])
                    }
                    aria-label="Количество последних сообщений в контексте"
                  />
                  <span className={styles.contextValue}>
                    {historyLimit} {historyLimit === 1 ? 'сообщение' : 'сообщений'}
                  </span>
                </div>
                <div className={styles.contextTicks}>
                  {HISTORY_OPTIONS.map((value) => (
                    <button
                      key={value}
                      type="button" className={styles.contextTick}
                      data-active={value === historyLimit || undefined}
                      onClick={() => setHistoryLimit(value)}
                    >
                      {value}
                    </button>
                  ))}
                </div>
                <p className={styles.hint}>
                  Сейчас: примерно {formatCompact(historyLimit * 220)} токенов истории на запрос.
                  При 0 модель видит только промпт и текущий вопрос.
                </p>
              </div>
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader
              title="Модель и ответы"
            />
            <PanelBody>
              <div className={styles.stack}>
                <Field
                  label="Модель по умолчанию" hint="Для быстрых чатов и режимов без своей модели."
                >
                  <Select
                    value={defaultModelId}
                    options={models.map((model) => ({
                      value: model.id,
                      label: model.name,
                      description: model.provider,
                      meta: `${formatCompact(model.context_window)}`,
                    }))}
                    onChange={setDefaultModelId}
                    ariaLabel="Модель по умолчанию"
                  />
                </Field>

                <Switch
                  checked={streamResponses}
                  onChange={setStreamResponses}
                  label="Потоковая выдача ответа" description="Показывать текст по мере генерации."
                />

                <Field
                  label="Хранение истории" hint="Срок хранения сообщений до автоочистки."
                >
                  <Select
                    value={retention}
                    options={RETENTION_OPTIONS}
                    onChange={setRetention}
                    ariaLabel="Срок хранения истории"
                  />
                </Field>
              </div>
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader
              title="Подключение устройств" actions={
                <Link to="/devices" className={styles.link}>
                  Управлять устройствами
                </Link>
              }
            />
            <PanelBody>
              <div className={styles.stack}>
                {liveCodes.length > 0 ? (
                  <ul className={styles.codeList}>
                    {liveCodes.map((code) => (
                      <li key={code.code} className={styles.codeRow}>
                        <KeyRound />
                        <span className={styles.codeValue}>{code.code}</span>
                        <span className={styles.codeMeta}>
                          действует до{' '}
                          {new Date(code.expires_at).toLocaleTimeString('ru-RU', {
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </span>
                        <span className={styles.codeMeta}>
                          создан {formatRelativeTime(code.created_at)}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className={styles.hint}>
                    Активных кодов нет. Код подключения выпускается в разделе «Устройства» и
                    действует 10 минут.
                  </p>
                )}
                <div className={styles.dangerInline}>
                  <div className={styles.dangerInlineText}>
                    <strong>Отключить текущую веб-панель</strong>
                    <span>
                      Завершает сессию этой панели. Данные режимов, чатов и источников сохраняются.
                    </span>
                  </div>
                  <Button variant="secondary" iconLeft={<Monitor />} onClick={disconnectPanel}>
                    Отключить
                  </Button>
                </div>
              </div>
            </PanelBody>
          </Panel>
        </div>

        <div className={styles.side}>
          <Panel>
            <PanelHeader title="Оформление" />
            <PanelBody>
              <div className={styles.stack}>
                <SegmentedControl<Theme>
                  value={theme}
                  onChange={setTheme}
                  aria-label="Тема оформления" options={[
                    { value: 'dark', label: 'Тёмная', icon: <Moon /> },
                    { value: 'light', label: 'Светлая', icon: <Sun /> },
                  ]}
                />
                <p className={styles.hint}>
                  Тема применяется к панели и запоминается в браузере. Часы используют собственную
                  тему Wear OS.
                </p>
              </div>
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader title="Режим разработчика" />
            <PanelBody>
              <Switch
                checked={developerMode}
                onChange={setDeveloperMode}
                label="Разрешить редактирование внутренних промптов" description="После сохранения появится раздел «Промпты»."
              />
            </PanelBody>
          </Panel>
        </div>
      </div>

      {dirty && (
        <div className={styles.saveBar}>
          <span className={styles.saveBarText}>
            <AlertTriangle /> Есть несохранённые изменения
          </span>
          <div className={styles.saveBarActions}>
            <Button variant="ghost" onClick={reset} disabled={saving}>
              Отменить
            </Button>
            <Button
              variant="primary" iconLeft={<Save />}
              onClick={save}
              loading={saving}
              disabled={saving}
            >
              Сохранить настройки
            </Button>
          </div>
        </div>
      )}
    </Page>
  );
}
