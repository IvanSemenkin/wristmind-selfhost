import { useRef } from 'react';
import { createPortal } from 'react-dom';
import type { ReactNode } from 'react';
import { X } from 'lucide-react';
import { cn } from '@/lib/cn';
import { useEscapeKey, useFocusTrap, useScrollLock } from '@/lib/hooks';
import { IconButton } from './Button';
import styles from './Modal.module.css';

/* -------------------------------------------------------------------------- */
/* Shared overlay internals                                                   */
/* -------------------------------------------------------------------------- */

interface SurfaceProps {
  onClose: () => void;
  dismissible: boolean;
  className: string;
  label: string;
  children: ReactNode;
}

/**
 * Mounted only while visible, so the focus trap and scroll lock activate for
 * exactly the lifetime of the overlay.
 */
function Overlay({ onClose, dismissible, className, label, children }: SurfaceProps) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, true);
  useScrollLock(true);
  useEscapeKey(() => {
    // A nested rename dialog or portalled row menu owns Escape first.
    if (document.querySelector('[role="menu"]')) return;
    const dialogs = document.querySelectorAll('[role="dialog"]');
    if (dialogs[dialogs.length - 1] !== ref.current) return;
    if (dismissible) onClose();
  }, true);

  return createPortal(
    <div className={styles.overlay}>
      <div
        className={styles.scrim}
        onClick={() => {
          if (dismissible) onClose();
        }}
      />
      <div ref={ref} role="dialog" aria-modal="true" aria-label={label} className={className}>
        {children}
      </div>
    </div>,
    document.body,
  );
}

interface HeaderProps {
  eyebrow?: ReactNode;
  title?: ReactNode;
  description?: ReactNode;
  onClose: () => void;
  showClose: boolean;
}

function OverlayHeader({ eyebrow, title, description, onClose, showClose }: HeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.headerText}>
        {eyebrow && <div className={styles.eyebrow}>{eyebrow}</div>}
        {title && <h2 className={styles.title}>{title}</h2>}
        {description && <p className={styles.description}>{description}</p>}
      </div>
      {showClose && <IconButton label="Закрыть" icon={<X />} size="sm" onClick={onClose} />}
    </header>
  );
}

/* -------------------------------------------------------------------------- */
/* Modal                                                                      */
/* -------------------------------------------------------------------------- */

export type ModalSize = 'sm' | 'md' | 'lg' | 'xl';

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  description?: ReactNode;
  size?: ModalSize;
  footer?: ReactNode;
  children: ReactNode;
  /** Set false for flows that must be resolved by an explicit action. */
  dismissible?: boolean;
  eyebrow?: ReactNode;
  /** Disable inner scrolling when the body manages its own layout. */
  bodyScroll?: boolean;
}

export function Modal({
  open,
  onClose,
  title,
  description,
  size = 'md',
  footer,
  children,
  dismissible = true,
  eyebrow,
  bodyScroll = true,
}: ModalProps) {
  if (!open) return null;

  return (
    <Overlay
      onClose={onClose}
      dismissible={dismissible}
      label={typeof title === 'string' ? title : 'Диалог'}
      className={cn(styles.panel, styles[size])}
      key={size}
    >
      <>
        {(title || eyebrow || description) && (
          <OverlayHeader
            eyebrow={eyebrow}
            title={title}
            description={description}
            onClose={onClose}
            showClose={dismissible}
          />
        )}
        <div className={cn(styles.body, !bodyScroll && styles.bodyNoScroll)}>{children}</div>
        {footer && <footer className={styles.footer}>{footer}</footer>}
      </>
    </Overlay>
  );
}

/* -------------------------------------------------------------------------- */
/* Drawer                                                                     */
/* -------------------------------------------------------------------------- */

export type DrawerSize = 'sm' | 'md' | 'lg';

export interface DrawerProps {
  side?: 'right' | 'left';
  bodyScroll?: boolean;
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  description?: ReactNode;
  size?: DrawerSize;
  footer?: ReactNode;
  children: ReactNode;
  eyebrow?: ReactNode;
}

export function Drawer({
  open,
  side = 'right',
  bodyScroll = true,
  onClose,
  title,
  description,
  size = 'md',
  footer,
  children,
  eyebrow,
}: DrawerProps) {
  if (!open) return null;

  return (
    <Overlay
      onClose={onClose}
      dismissible
      label={typeof title === 'string' ? title : 'Панель'}
      className={cn(styles.drawer, styles[`drawer_${size}`], side === 'left' && styles.drawerLeft)}
      key={size}
    >
      <>
        <OverlayHeader
          eyebrow={eyebrow}
          title={title}
          description={description}
          onClose={onClose}
          showClose
        />
        <div className={cn(styles.body, !bodyScroll && styles.bodyNoScroll)}>{children}</div>
        {footer && <footer className={styles.footer}>{footer}</footer>}
      </>
    </Overlay>
  );
}
