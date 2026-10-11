import { useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Check, ChevronDown } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Menu } from './Menu';
import type { MenuEntry } from './Menu';
import styles from './Select.module.css';

export interface SelectOption<T extends string> {
  value: T;
  label: string;
  description?: string;
  icon?: ReactNode;
  /** Small trailing hint, e.g. a context window or provider. */
  meta?: string;
}

export interface SelectProps<T extends string> {
  value: T | null;
  options: SelectOption<T>[];
  onChange: (value: T) => void;
  placeholder?: string;
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  invalid?: boolean;
  className?: string;
  id?: string;
  /** Renders the options under group headings. */
  groups?: Array<{ label: string; values: T[] }>;
  ariaLabel?: string;
}

export function Select<T extends string>({
  value,
  options,
  onChange,
  placeholder = 'Выберите значение',
  size = 'md',
  disabled = false,
  invalid = false,
  className,
  id,
  groups,
  ariaLabel,
}: SelectProps<T>) {
  const anchor = useRef<HTMLDivElement | null>(null);
  const [menuWidth, setMenuWidth] = useState<number | undefined>(undefined);

  const selected = options.find((o) => o.value === value) ?? null;

  const entryFor = (option: SelectOption<T>): MenuEntry => ({
    type: 'item',
    id: option.value,
    label: option.label,
    description: option.description,
    icon: option.icon,
    shortcut: option.meta,
    checked: option.value === value,
    onSelect: () => onChange(option.value),
  });

  const entries: MenuEntry[] = groups
    ? groups.flatMap((group) => [
        { type: 'label' as const, id: `g_${group.label}`, label: group.label },
        ...options.filter((o) => group.values.includes(o.value)).map(entryFor),
      ])
    : options.map(entryFor);

  return (
    <div ref={anchor} className={cn(styles.wrap, className)}>
      <Menu
        align="start" width={menuWidth} variant="select"
        onOpenChange={(open) => {
          if (open) setMenuWidth(Math.max(anchor.current?.offsetWidth ?? 0, 220));
        }}
        trigger={
          <button
            type="button" id={id}
            disabled={disabled}
            aria-label={ariaLabel}
            className={styles.trigger}
            data-size={size}
            data-invalid={invalid || undefined}
            data-placeholder={!selected || undefined}
          >
            {selected?.icon && <span className={styles.icon}>{selected.icon}</span>}
            <span className={styles.value}>{selected ? selected.label : placeholder}</span>
            {selected?.meta && <span className={styles.meta}>{selected.meta}</span>}
            <ChevronDown className={styles.chevron} />
          </button>
        }
        entries={entries}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Multi-line listbox used for model picking                                  */
/* -------------------------------------------------------------------------- */

export interface ModelPickerOption<T extends string> {
  value: T;
  label: string;
  description: string;
  meta: string;
  icon?: ReactNode;
}

export function OptionList<T extends string>({
  value,
  options,
  onChange,
  className,
}: {
  value: T | null;
  options: ModelPickerOption<T>[];
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div className={cn(styles.optionList, className)} role="radiogroup">
      {options.map((option) => (
        <button
          key={option.value}
          type="button" role="radio"
          aria-checked={option.value === value}
          className={styles.option}
          data-active={option.value === value || undefined}
          onClick={() => onChange(option.value)}
        >
          <span className={styles.optionCheck}>
            {option.value === value ? <Check /> : option.icon}
          </span>
          <span className={styles.optionBody}>
            <span className={styles.optionHead}>
              <span className={styles.optionLabel}>{option.label}</span>
              <span className={styles.optionMeta}>{option.meta}</span>
            </span>
            <span className={styles.optionDescription}>{option.description}</span>
          </span>
        </button>
      ))}
    </div>
  );
}
