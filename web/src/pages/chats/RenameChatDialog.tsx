import { useEffect, useState } from 'react';
import { useActions } from '@/services';
import type { Chat } from '@/types';
import { Button, Field, Input, Modal, useToast } from '@/components';

export function RenameChatDialog({ chat, onClose }: { chat: Chat | null; onClose: () => void }) {
  const actions = useActions();
  const toast = useToast();
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!chat) return;
    setValue(chat.title);
    setBusy(false);
  }, [chat]);

  const submit = async () => {
    if (!chat || value.trim().length === 0) return;
    setBusy(true);
    try {
      await actions.updateChat(chat.id, { title: value.trim() });
      toast.success('Чат переименован', value.trim());
      onClose();
    } catch {
      toast.error('Не удалось переименовать чат');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={chat !== null}
      onClose={onClose}
      size="sm" title="Переименовать чат" description="Видно только в панели." footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Отмена
          </Button>
          <Button
            variant="primary" onClick={submit}
            loading={busy}
            disabled={value.trim().length === 0}
          >
            Сохранить
          </Button>
        </>
      }
    >
      <Field label="Название чата" htmlFor="rename-chat">
        <Input
          id="rename-chat" value={value}
          autoFocus
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void submit();
          }}
        />
      </Field>
    </Modal>
  );
}
