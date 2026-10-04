import { useEffect, useMemo, useState } from 'react';
import { Eye, Sparkles } from 'lucide-react';
import { describeError, useActions } from '@/services';
import { useModels, useSettings } from '@/store';
import type { Mode, ModeColor } from '@/types';
import { MODE_COLORS } from '@/types';
import { cn } from '@/lib/cn';
import { Button, Field, Input, Modal, Select, Switch, Textarea, useToast } from '@/components';
import { capabilityLabel } from '@/components/Entities';
import styles from './ModeFormDialog.module.css';

export interface ModeFormDialogProps {
  open: boolean;
  onClose: () => void;
  /** Pass a mode to edit; omit to create. */
  mode?: Mode | null;
  onSaved?: (mode: Mode) => void;
}

interface FormState {
  name: string;
  description: string;
  color: ModeColor;
  response_model_id: string;
  system_prompt: string;
  hidden_on_watch: boolean;
}

const EMPTY: FormState = {
  name: '',
  description: '',
  color: 'blue',
  response_model_id: '',
  system_prompt: '',
  hidden_on_watch: false,
};

const PROMPT_TEMPLATE = `Ты — ассистент режима «{name}».

Правила:
1. Отвечай кратко и по делу.
2. Опирайся на базу знаний режима и ссылайся на источники.
3. Если данных недостаточно — скажи об этом прямо.`;

export function ModeFormDialog({ open, onClose, mode, onSaved }: ModeFormDialogProps) {
  const models = useModels();
  const settings = useSettings();
  const actions = useActions();
  const toast = useToast();
  const editing = Boolean(mode);

  const [form, setForm] = useState<FormState>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTouched(false);
    setSaving(false);
    setForm(
      mode
        ? {
            name: mode.name,
            description: mode.description,
            color: mode.color,
            response_model_id: mode.response_model_id,
            system_prompt: mode.system_prompt,
            hidden_on_watch: mode.hidden_on_watch,
          }
        : EMPTY,
    );
    if (open && !mode) {
      setForm((current) => ({
        ...current,
        response_model_id: settings?.default_model_id || models[0]?.id || '',
      }));
    }
  }, [open, mode, settings?.default_model_id, models]);

  const nameError = touched && form.name.trim().length < 2 ? 'Укажите название режима' : null;
  const promptError =
    touched && form.system_prompt.trim().length < 10 ? 'Системный промпт слишком короткий' : null;
  const modelError =
    touched && !models.some((model) => model.id === form.response_model_id)
      ? models.length === 0
        ? 'Список моделей не загрузился. Обновите страницу.'
        : 'Выберите модель'
      : null;

  const modelOptions = useMemo(
    () =>
      models.map((model) => ({
        value: model.id,
        label: model.name,
        description: `${model.provider} · ${capabilityLabel(model.capabilities[0])}`,
        meta: `${Math.round(model.context_window / 1000)}K`,
      })),
    [models],
  );

  const patch = (next: Partial<FormState>) => setForm((current) => ({ ...current, ...next }));

  const submit = async () => {
    setTouched(true);
    if (
      form.name.trim().length < 2 ||
      form.system_prompt.trim().length < 10 ||
      !models.some((model) => model.id === form.response_model_id)
    ) return;

    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim(),
        color: form.color,
        system_prompt: form.system_prompt.trim(),
        response_model_id: form.response_model_id,
        hidden_on_watch: form.hidden_on_watch,
      };
      const saved = mode
        ? await actions.updateMode(mode.id, payload)
        : await actions.createMode(payload);
      toast.success(editing ? 'Режим обновлён' : 'Режим создан', saved.name);
      onSaved?.(saved);
      onClose();
    } catch (error) {
      toast.error(
        'Не удалось сохранить режим',
        describeError(error, 'Повторите попытку'),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg" title={editing ? 'Настройки режима' : 'Новый режим'}
      description={
        editing
          ? 'Изменения применятся к новым сообщениям.'
          : 'Режим — своя модель, промпт и база знаний.'
      }
      bodyScroll
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Отмена
          </Button>
          <Button variant="primary" onClick={submit} loading={saving}>
            {editing ? 'Сохранить' : 'Создать режим'}
          </Button>
        </>
      }
    >
      <div className={styles.grid}>
        <div className={styles.main}>
          <Field label="Название" required error={nameError} htmlFor="mode-name">
            <Input
              id="mode-name" value={form.name}
              autoFocus
              placeholder="Например, «Рабочий ассистент»" invalid={Boolean(nameError)}
              onChange={(e) => patch({ name: e.target.value })}
            />
          </Field>

          <Field
            label="Описание" hint="Видно только в панели." htmlFor="mode-description"
          >
            <Textarea
              id="mode-description" rows={2}
              value={form.description}
              placeholder="Коротко: какие задачи решает режим" onChange={(e) => patch({ description: e.target.value })}
            />
          </Field>

          <Field
            label="Системный промпт"
            required
            error={promptError}
            meta={`${form.system_prompt.length} символов`}
            hint="Инструкции для модели в этом режиме."
          >
            <Textarea
              rows={9}
              mono
              value={form.system_prompt}
              invalid={Boolean(promptError)}
              placeholder={PROMPT_TEMPLATE.replace('{name}', form.name || '…')}
              onChange={(e) => patch({ system_prompt: e.target.value })}
            />
          </Field>

          {form.system_prompt.trim().length === 0 && (
            <button
              type="button" className={styles.templateButton}
              onClick={() =>
                patch({ system_prompt: PROMPT_TEMPLATE.replace('{name}', form.name || 'режима') })
              }
            >
              <Sparkles />
              Вставить шаблон промпта
            </button>
          )}
        </div>

        <aside className={styles.side}>
          <Field label="Цвет режима" hint="Видно в списках и на часах.">
            <ColorSwatchRow value={form.color} onChange={(color) => patch({ color })} />
          </Field>

          <Field
            label="Модель"
            required
            error={modelError}
            hint="Можно сменить позже."
          >
            <Select
              value={form.response_model_id}
              options={modelOptions}
              onChange={(value) => patch({ response_model_id: value })}
              ariaLabel="Модель режима" invalid={Boolean(modelError)}
              disabled={models.length === 0}
            />
          </Field>

          <div className={styles.switchBox}>
            <Switch
              checked={!form.hidden_on_watch}
              onChange={(visible) => patch({ hidden_on_watch: !visible })}
              label="Показывать на часах" description="Режим появится в списке на часах."
            />
            {!form.hidden_on_watch && (
              <span className={styles.watchHint}>
                <Eye /> Режим будет доступен с часов
              </span>
            )}
          </div>

          <div className={styles.preview} data-mode-color={form.color}>
            <span className={styles.previewDot} />
            <div className={styles.previewText}>
              <span className={styles.previewName}>{form.name || 'Новый режим'}</span>
              <span className={styles.previewMeta}>
                {models.find((m) => m.id === form.response_model_id)?.name ?? 'Модель'}
              </span>
            </div>
          </div>
        </aside>
      </div>
    </Modal>
  );
}

export function ColorSwatchRow({
  value,
  onChange,
  className,
}: {
  value: ModeColor;
  onChange: (color: ModeColor) => void;
  className?: string;
}) {
  return (
    <div className={cn(styles.colors, className)} role="radiogroup" aria-label="Цвет режима">
      {MODE_COLORS.map((color) => (
        <button
          key={color}
          type="button" role="radio"
          aria-checked={value === color}
          aria-label={color}
          data-mode-color={color}
          data-active={value === color || undefined}
          className={styles.colorSwatch}
          onClick={() => onChange(color)}
        />
      ))}
    </div>
  );
}
