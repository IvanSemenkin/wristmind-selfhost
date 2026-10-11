import { Link } from '@/app/router';
import { Compass, Watch } from 'lucide-react';
import { cn } from '@/lib/cn';
import styles from './App.module.css';

/* -------------------------------------------------------------------------- */
/* Boot screen                                                                */
/* -------------------------------------------------------------------------- */

/** Skeleton shell shown while the API bootstrap resolves. */
export function BootScreen({ className }: { className?: string }) {
  return (
    <div className={cn(styles.boot, className)} role="status" aria-label="Загрузка панели">
      <div className={styles.bootSidebar}>
        <div className={styles.bootBrand}>
          <span className={styles.bootMark}>
            <Watch />
          </span>
          <span className={styles.bootBrandText} />
        </div>
        {Array.from({ length: 6 }, (_, i) => (
          <span key={i} className={styles.bootNavItem} style={{ opacity: 1 - i * 0.12 }} />
        ))}
      </div>
      <div className={styles.bootMain}>
        <div className={styles.bootTopbar} />
        <div className={styles.bootContent}>
          <span className={styles.bootTitle} />
          <span className={styles.bootSubtitle} />
          <div className={styles.bootStrip}>
            {Array.from({ length: 4 }, (_, i) => (
              <span key={i} className={styles.bootMetric} />
            ))}
          </div>
          <div className={styles.bootPanels}>
            <span className={styles.bootPanel} />
            <span className={styles.bootPanel} />
          </div>
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Error state                                                                */
/* -------------------------------------------------------------------------- */

export function BootError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className={styles.bootError}>
      <div className={styles.bootErrorCard}>
        <h1>Не удалось загрузить панель</h1>
        <p>{message}</p>
        <button type="button" className={styles.bootErrorButton} onClick={onRetry}>
          Повторить
        </button>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 404                                                                        */
/* -------------------------------------------------------------------------- */

export function NotFoundPage() {
  return (
    <div className={styles.notFound}>
      <span className={styles.notFoundIcon}>
        <Compass />
      </span>
      <h1 className={styles.notFoundTitle}>Страница не найдена</h1>
      <p className={styles.notFoundText}>
        Раздел мог быть перемещён или удалён. Проверьте адрес или вернитесь к обзору системы.
      </p>
      <Link to="/" className={styles.notFoundLink}>
        Вернуться к обзору
      </Link>
    </div>
  );
}
