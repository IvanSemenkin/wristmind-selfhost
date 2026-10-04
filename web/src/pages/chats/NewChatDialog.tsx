import { useEffect, useMemo, useState } from 'react';
import { BookOpen, MessagesSquare, Zap } from 'lucide-react';
import { useActions } from '@/services';
import { useModels, useModes, useSources } from '@/store';
import { useNavigate } from '@/app/router';
import { cn } from '@/lib/cn';
import { Button, Field, Input, Modal, useToast } from '@/components';
import { ModeDot } from '@/components/Entities';
import styles from './NewChatDialog.module.css';

export interface NewChatDialogProps {
  open: boolean;
  onClose: () => void;
  /** Preselects a mode; `null` means "quick chat". */
  initialModeId?: string | null;
  onCreated?: (chatId: string) => void;
}

const QUICK = '__quick__';

export function NewChatDialog({ open, onClose, initialModeId, onCreated }: NewChatDialogProps) {
  const modes = useModes();
  const sources = useSources();
  const models = useModels();
  const actions = useActions();
  const toast = useToast();
  const navigate = useNavigate();

  const [selection, setSelection] = useState<string>(QUICK);
  const [title, setTitle] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setSelection(initialModeId ?? QUICK);
    setTitle('');
    setSaving(false);
  }, [open, initialModeId]);

  const sourceCount = useMemo(() => {
    const map = new Map<string, number>();
    for (const source of sources) {
      if (source.status !== 'ready') continue;
      map.set(source.mode_id, (map.get(source.mode_id) ?? 0) + 1);
    }
    return map;
  }, [sources]);

  const create = async () => {
    setSaving(true);
    try {
      const chat = await actions.createChat(
        selection === QUICK ? null : selection,
        title.trim() || undefined,
      );
      toast.success('Чат создан', selection === QUICK ? 'Быстрый чат без базы знаний' : undefined);
      onCreated?.(chat.id);
      onClose();
      navigate(`/chats/${chat.id}`);
    } catch {
      toast.error('Не удалось создать чат');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="md" title="Новый чат" description="От режима зависят модель и база знаний." footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Отмена
          </Button>
          <Button variant="primary" onClick={create} loading={saving} iconLeft={<MessagesSquare />}>
            Создать чат
          </Button>
        </>
      }
    >
      <div className={styles.body}>
        <div className={styles.options} role="radiogroup" aria-label="Режим чата">
          <button
            type="button" role="radio"
            aria-checked={selection === QUICK}
            className={styles.option}
            data-active={selection === QUICK || undefined}
            onClick={() => setSelection(QUICK)}
          >
            <span className={styles.optionIcon} data-quick>
              <Zap />
            </span>
            <span className={styles.optionBody}>
              <span className={styles.optionHead}>
                <span className={styles.optionName}>Быстрый чат</span>
                <span className={styles.optionTag}>без базы знаний</span>
              </span>
              <span className={styles.optionDescription}>
                Общие ответы модели без поиска по источникам. Подходит для разовых вопросов.
              </span>
            </span>
          </button>

          {modes.map((mode) => {
            const model = models.find((m) => m.id === mode.response_model_id);
            const count = sourceCount.get(mode.id) ?? 0;
            return (
              <button
                key={mode.id}
                type="button" role="radio"
                aria-checked={selection === mode.id}
                className={styles.option}
                data-active={selection === mode.id || undefined}
                data-mode-color={mode.color}
                onClick={() => setSelection(mode.id)}
              >
                <span className={styles.optionIcon} data-mode-color={mode.color}>
                  <ModeDot color={mode.color} icon={mode.icon} size="md" />
                </span>
                <span className={styles.optionBody}>
                  <span className={styles.optionHead}>
                    <span className={styles.optionName}>{mode.name}</span>
                    <span className={styles.optionTag}>{model?.name ?? 'модель не выбрана'}</span>
                  </span>
                  <span className={styles.optionDescription}>
                    {mode.description || 'Без описания'}
                  </span>
                  <span className={cn(styles.optionMeta, count === 0 && styles.optionMetaWarning)}>
                    <BookOpen />
                    {count === 0
                      ? 'Нет готовых источников — ответы будут без ссылок'
                      : `${count} ${count === 1 ? 'источник' : count < 5 ? 'источника' : 'источников'} в базе знаний`}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        <Field
          label="Название" hint="Иначе название возьмётся из первого сообщения." htmlFor="chat-title"
        >
          <Input
            id="chat-title" value={title}
            placeholder="Например, «Регламент деплоя»" onChange={(e) => setTitle(e.target.value)}
          />
        </Field>
      </div>
    </Modal>
  );
}
