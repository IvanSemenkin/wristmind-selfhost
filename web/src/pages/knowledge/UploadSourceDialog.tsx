import { useEffect, useMemo, useState } from 'react';
import { BookOpen, Image as ImageIcon, Upload, X } from 'lucide-react';
import { useActions } from '@/services';
import { useModes } from '@/store';
import {
  ACCEPT_ATTRIBUTE,
  ACCEPTED_MEDIA_TYPES,
  PROCESSING_MODES,
  type ProcessingMode,
  type SourceKind,
} from '@/types';
import { formatBytes } from '@/lib/format';
import {
  Banner,
  Button,
  Field,
  Input,
  Modal,
  Select,
  useToast,
} from '@/components';
import styles from './UploadSourceDialog.module.css';

export interface UploadSourceDialogProps {
  open: boolean;
  onClose: () => void;
  initialModeId?: string | null;
  onUploaded?: (sourceId: string) => void;
}

interface PickedFile {
  file: File;
  name: string;
  size: number;
  kind: SourceKind;
}

const MAX_SIZE = 32 * 1024 * 1024;

function classify(fileName: string, mime: string): SourceKind {
  if (mime.startsWith('image/')) return 'image';
  if (mime === 'application/pdf') return 'pdf';
  return /\.(png|jpe?g|webp)$/i.test(fileName) ? 'image' : 'pdf';
}

export function UploadSourceDialog({
  open,
  onClose,
  initialModeId,
  onUploaded,
}: UploadSourceDialogProps) {
  const modes = useModes();
  const actions = useActions();
  const toast = useToast();

  const [modeId, setModeId] = useState<string>('');
  const [picked, setPicked] = useState<PickedFile | null>(null);
  const [title, setTitle] = useState('');
  const [processingMode, setProcessingMode] = useState<ProcessingMode>('OCR');
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setModeId(initialModeId ?? modes[0]?.id ?? '');
    setPicked(null);
    setTitle('');
    setProcessingMode('OCR');
    setError(null);
    setSaving(false);
    setDragging(false);
  }, [open, initialModeId, modes]);

  const modeOptions = useMemo(
    () =>
      modes.map((mode) => ({
        value: mode.id,
        label: mode.name,
        description: mode.description,
      })),
    [modes],
  );

  const accept = (file: File) => {
    if (file.size > MAX_SIZE) {
      setError(`Файл больше ${formatBytes(MAX_SIZE)}. Разделите документ и загрузите частями.`);
      return;
    }
    const kind = classify(file.name, file.type);
    setError(null);
    setPicked({ file, name: file.name, size: file.size, kind });
    setTitle(file.name.replace(/\.[^.]+$/, ''));
    setProcessingMode(kind === 'image' ? 'VISION' : 'OCR');
  };

  const handleFiles = (files: FileList | null) => {
    const first = files?.[0];
    if (first) accept(first);
  };

  const submit = async () => {
    if (!picked) {
      setError('Выберите PDF-файл или изображение');
      return;
    }
    if (!modeId) {
      setError('Выберите режим');
      return;
    }
    if (title.trim().length < 2) {
      setError('Укажите название источника');
      return;
    }

    setSaving(true);
    try {
      const source = await actions.uploadSource({
        mode_id: modeId,
        title: title.trim(),
        file: picked.file,
        processing_mode: processingMode,
      });
      toast.success(
        'Источник добавлен',
        'Обработка запущена в фоне — прогресс виден в базе знаний режима.',
      );
      onUploaded?.(source.id);
      onClose();
    } catch {
      toast.error('Не удалось загрузить источник');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="md" title="Загрузить источник" description="Файл попадёт в базу знаний выбранного режима." footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Отмена
          </Button>
          <Button variant="primary" onClick={submit} loading={saving} iconLeft={<Upload />}>
            Загрузить и обработать
          </Button>
        </>
      }
    >
      <div className={styles.body}>
        <Field label="Режим" required hint="База знаний каждого режима изолирована.">
          <Select
            value={modeId || null}
            options={modeOptions}
            onChange={setModeId}
            placeholder="Выберите режим" ariaLabel="Режим для источника"
          />
        </Field>

        <Field label="Файл" required>
          {picked ? (
            <div className={styles.fileChip}>
              <span className={styles.fileIcon} data-kind={picked.kind}>
                {picked.kind === 'image' ? <ImageIcon /> : <BookOpen />}
              </span>
              <span className={styles.fileMeta}>
                <span className={styles.fileName}>{picked.name}</span>
                <span className={styles.fileSub}>
                  {picked.kind === 'image' ? 'Изображение' : 'PDF-документ'} ·{' '}
                  {formatBytes(picked.size)}
                </span>
              </span>
              <label className={styles.fileReplace}>
                <input
                  type="file"
                  hidden
                  accept={ACCEPT_ATTRIBUTE}
                  onChange={(e) => {
                    handleFiles(e.target.files);
                    e.target.value = '';
                  }}
                />
                <span>Заменить</span>
              </label>
              <Button size="sm" variant="ghost" iconLeft={<X />} onClick={() => setPicked(null)}>
                Убрать
              </Button>
            </div>
          ) : (
            <label
              className={styles.dropzone}
              data-dragging={dragging || undefined}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                handleFiles(e.dataTransfer.files);
              }}
            >
              <input
                type="file"
                hidden
                accept={ACCEPT_ATTRIBUTE}
                onChange={(e) => {
                  handleFiles(e.target.files);
                  e.target.value = '';
                }}
              />
              <span className={styles.dropIcon}>
                <Upload />
              </span>
              <span className={styles.dropTitle}>Перетащите файл или нажмите для выбора</span>
              <span className={styles.dropHint}>
                PDF, JPG, JPEG, PNG, WEBP · до {formatBytes(MAX_SIZE)}
              </span>
            </label>
          )}
        </Field>

        <Field
          label="Название"
          required
          hint="Название в поиске и ссылках." htmlFor="source-title"
        >
          <Input
            id="source-title" value={title}
            placeholder="Например, «Регламент релизов v4»" onChange={(e) => setTitle(e.target.value)}
          />
        </Field>

        <Field
          label="Способ обработки" hint="OCR — текст, Vision — структура и таблицы."
        >
          <div className={styles.methodNotes}>
            <button
              type="button" className={styles.methodNote}
              data-active={processingMode === 'OCR' || undefined}
              aria-pressed={processingMode === 'OCR'}
              onClick={() => setProcessingMode('OCR')}
            >
              <strong>OCR</strong>
              <span>Быстрее и дешевле. Хорошо работает с текстовыми PDF и чёткими сканами.</span>
            </button>
            <button
              type="button" className={styles.methodNote}
              data-active={processingMode === 'VISION' || undefined}
              aria-pressed={processingMode === 'VISION'}
              onClick={() => setProcessingMode('VISION')}
            >
              <strong>Vision</strong>
              <span>
                Разбирает таблицы, схемы, рукописный текст и подписи. Медленнее и требует
                vision-модель.
              </span>
            </button>
          </div>
        </Field>

        {processingMode === 'VISION' && picked?.kind === 'pdf' && (
          <Banner tone="warning" icon={<ImageIcon />} title="Vision для PDF">
            Vision обрабатывает страницы постранично как изображения. Для больших документов это
            заметно дольше — рассмотрите OCR, если текст в PDF уже выделяется.
          </Banner>
        )}

        {error && (
          <Banner tone="danger" icon={<X />} title="Проверьте форму">
            {error}
          </Banner>
        )}

        <p className={styles.footnote}>
          Загрузка возвращает фоновую задачу: источник проходит состояния «загрузка» → «обработка» →
          «готово» или «ошибка», а список обновляется без перезагрузки страницы. Поддерживаются{' '}
          {ACCEPTED_MEDIA_TYPES.length} типов файлов и режимы {PROCESSING_MODES.join(' / ')}.
        </p>
      </div>
    </Modal>
  );
}
