import { useId } from 'react';
import type { ComponentPropsWithRef, ReactNode } from 'react';
import { Search, X } from 'lucide-react';
import { cn } from '@/lib/cn';
import { IconButton } from './Button';
import styles from './Field.module.css';

/* -------------------------------------------------------------------------- */
/* Field wrapper                                                              */
/* -------------------------------------------------------------------------- */

export interface FieldProps {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  /** Right-aligned meta text in the label row (counters, "необязательно"). */
  meta?: ReactNode;
  htmlFor?: string;
  required?: boolean;
  children: ReactNode;
  className?: string;
}

export function Field({
  label,
  hint,
  error,
  meta,
  htmlFor,
  required,
  children,
  className,
}: FieldProps) {
  return (
    <div className={cn(styles.field, className)}>
      {(label || meta) && (
        <div className={styles.fieldHead}>
          {label && (
            <label className={styles.fieldLabel} htmlFor={htmlFor}>
              {label}
              {required && <span className={styles.required}>*</span>}
            </label>
          )}
          {meta && <span className={styles.fieldMeta}>{meta}</span>}
        </div>
      )}
      {children}
      {error ? (
        <p className={styles.fieldError}>{error}</p>
      ) : (
        hint && <p className={styles.fieldHint}>{hint}</p>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Input                                                                      */
/* -------------------------------------------------------------------------- */

export type InputSize = 'sm' | 'md' | 'lg';

export interface InputProps extends Omit<ComponentPropsWithRef<'input'>, 'size'> {
  size?: InputSize;
  invalid?: boolean;
  iconLeft?: ReactNode;
  iconRight?: ReactNode;
  /** Monospace, tabular — for codes, numbers and identifiers. */
  mono?: boolean;
}

export function Input({
  size = 'md',
  invalid = false,
  iconLeft,
  iconRight,
  mono = false,
  className,
  ...rest
}: InputProps) {
  return (
    <div
      className={cn(styles.control, className)}
      data-size={size}
      data-invalid={invalid || undefined}
      data-disabled={rest.disabled || undefined}
    >
      {iconLeft && <span className={styles.controlIcon}>{iconLeft}</span>}
      <input {...rest} className={styles.input} data-mono={mono || undefined} />
      {iconRight && <span className={styles.controlIconRight}>{iconRight}</span>}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Textarea                                                                   */
/* -------------------------------------------------------------------------- */

export interface TextareaProps extends ComponentPropsWithRef<'textarea'> {
  invalid?: boolean;
  mono?: boolean;
  autoGrow?: boolean;
}

export function Textarea({
  invalid = false,
  mono = false,
  className,
  rows = 4,
  ...rest
}: TextareaProps) {
  return (
    <div
      className={cn(styles.control, styles.textareaWrap, className)}
      data-invalid={invalid || undefined}
      data-disabled={rest.disabled || undefined}
    >
      <textarea {...rest} rows={rows} className={styles.textarea} data-mono={mono || undefined} />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Search input                                                               */
/* -------------------------------------------------------------------------- */

export interface SearchInputProps extends Omit<ComponentPropsWithRef<'input'>, 'size'> {
  size?: InputSize;
  onClear?: () => void;
}

export function SearchInput({ value, onClear, className, size = 'md', ...rest }: SearchInputProps) {
  const hasValue = typeof value === 'string' && value.length > 0;
  return (
    <div
      className={cn(styles.control, styles.search, className)}
      data-size={size}
      data-disabled={rest.disabled || undefined}
    >
      <span className={styles.controlIcon}>
        <Search />
      </span>
      <input {...rest} value={value} type="search" className={styles.input} />
      {hasValue && onClear && (
        <span className={styles.clearSlot}>
          <IconButton size="xs" label="Очистить" icon={<X />} onClick={onClear} />
        </span>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Switch                                                                     */
/* -------------------------------------------------------------------------- */

export interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  id?: string;
  className?: string;
  /** Visually smaller switch used inside dense rows. */
  size?: 'sm' | 'md';
}

export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled = false,
  id,
  className,
  size = 'md',
}: SwitchProps) {
  const generated = useId();
  const inputId = id ?? generated;

  const control = (
    <button
      type="button" role="switch" id={inputId}
      aria-checked={checked}
      aria-label={typeof label === 'string' ? label : undefined}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={styles.switch}
      data-size={size}
      data-checked={checked || undefined}
    >
      <span className={styles.switchThumb} />
    </button>
  );

  if (!label && !description) return <span className={className}>{control}</span>;

  return (
    <div className={cn(styles.switchRow, className)} data-disabled={disabled || undefined}>
      <div className={styles.switchText}>
        {label && (
          <label className={styles.switchLabel} htmlFor={inputId}>
            {label}
          </label>
        )}
        {description && <p className={styles.switchDescription}>{description}</p>}
      </div>
      {control}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Segmented control                                                          */
/* -------------------------------------------------------------------------- */

export interface SegmentedOption<T extends string> {
  value: T;
  label: ReactNode;
  icon?: ReactNode;
}

export interface SegmentedControlProps<T extends string> {
  value: T;
  options: SegmentedOption<T>[];
  onChange: (value: T) => void;
  size?: 'sm' | 'md';
  className?: string;
  'aria-label'?: string;
}

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  size = 'md',
  className,
  'aria-label': ariaLabel,
}: SegmentedControlProps<T>) {
  return (
    <div className={cn(styles.segmented, className)} data-size={size} role="radiogroup" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button" role="radio"
          aria-checked={option.value === value}
          data-active={option.value === value || undefined}
          className={styles.segment}
          onClick={() => onChange(option.value)}
        >
          {option.icon}
          {option.label}
        </button>
      ))}
    </div>
  );
}
