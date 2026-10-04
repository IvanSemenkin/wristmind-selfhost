import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
} from 'react';
import type { AnchorHTMLAttributes, MouseEvent, ReactNode } from 'react';
import { normalizePath, resolveRoute, type RouteDefinition, type RouteParams } from './match';

/* =============================================================================
   Router.

   A ~150-line history-based router that mirrors the small slice of API the
   console needs. It exists so the UI is not coupled to a particular routing
   library: porting to the production WristMind shell means re-implementing this
   one module, not touching pages.
   ========================================================================== */

/* -------------------------------------------------------------------------- */
/* History store                                                              */
/* -------------------------------------------------------------------------- */

interface HistorySnapshot {
  pathname: string;
  search: string;
  hash: string;
  /** Increments on every navigation, including same-path pushes. */
  key: number;
}

let keyCounter = 0;
let snapshot: HistorySnapshot = readLocation();
const listeners = new Set<() => void>();

function readLocation(): HistorySnapshot {
  const { pathname, search, hash } = window.location;
  return { pathname: normalizePath(pathname), search, hash, key: keyCounter };
}

function notify(): void {
  snapshot = readLocation();
  for (const listener of listeners) listener();
}

function subscribeHistory(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getHistorySnapshot(): HistorySnapshot {
  return snapshot;
}

function pushHistory(to: string, replace: boolean): void {
  const url = new URL(to, window.location.origin);
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) return;
  keyCounter += 1;
  if (replace) window.history.replaceState(null, '', next);
  else window.history.pushState(null, '', next);
  notify();
}

window.addEventListener('popstate', notify);

/* -------------------------------------------------------------------------- */
/* Context                                                                    */
/* -------------------------------------------------------------------------- */

export interface RouterValue {
  pathname: string;
  search: string;
  hash: string;
  params: RouteParams;
  searchParams: URLSearchParams;
  /** The element matched for the current location, if any. */
  element: ReactNode;
  /** Rendered by `RouterOutlet` when nothing matched. */
  fallback: ReactNode;
  navigate: (to: string, options?: { replace?: boolean }) => void;
  back: () => void;
  /** Replaces the query string; `null` values remove a key. */
  setSearchParams: (next: Record<string, string | null>, options?: { replace?: boolean }) => void;
  isActive: (to: string, options?: { end?: boolean }) => boolean;
}

const RouterContext = createContext<RouterValue | null>(null);

export interface RouterProviderProps {
  routes: RouteDefinition[];
  /** Rendered when no route matches. */
  fallback: ReactNode;
  children: ReactNode;
}

export function RouterProvider({ routes, fallback, children }: RouterProviderProps) {
  const location = useSyncExternalStore(subscribeHistory, getHistorySnapshot, getHistorySnapshot);

  // Redirects are applied in an effect so rendering stays pure.
  const { route, params, redirect } = resolveRoute(routes, location.pathname);

  useEffect(() => {
    if (redirect) pushHistory(redirect, true);
  }, [redirect]);

  const navigate = useCallback((to: string, options?: { replace?: boolean }) => {
    pushHistory(to, options?.replace ?? false);
  }, []);

  const back = useCallback(() => {
    window.history.back();
  }, []);

  const setSearchParams = useCallback(
    (next: Record<string, string | null>, options?: { replace?: boolean }) => {
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(next)) {
        if (value !== null) params.set(key, value);
      }
      const query = params.toString();
      const path = window.location.pathname;
      pushHistory(query ? `${path}?${query}` : path, options?.replace ?? true);
    },
    [],
  );

  const isActive = useCallback(
    (to: string, options?: { end?: boolean }) => {
      const target = normalizePath(to);
      if (options?.end || target === '/') return location.pathname === target;
      return location.pathname === target || location.pathname.startsWith(`${target}/`);
    },
    [location.pathname],
  );

  const element = useMemo(() => {
    if (redirect || !route?.render) return null;
    return route.render(params) as ReactNode;
  }, [route, params, redirect]);

  const value = useMemo<RouterValue>(
    () => ({
      pathname: location.pathname,
      search: location.search,
      hash: location.hash,
      params,
      searchParams: new URLSearchParams(location.search),
      element,
      fallback,
      navigate,
      back,
      setSearchParams,
      isActive,
    }),
    [
      location.pathname,
      location.search,
      location.hash,
      params,
      element,
      fallback,
      navigate,
      back,
      setSearchParams,
      isActive,
    ],
  );

  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

/* -------------------------------------------------------------------------- */
/* Hooks                                                                      */
/* -------------------------------------------------------------------------- */

export function useRouter(): RouterValue {
  const value = useContext(RouterContext);
  if (!value) throw new Error('useRouter должен вызываться внутри RouterProvider');
  return value;
}

/**
 * Returns a callable navigator, so `const navigate = useNavigate(); navigate(to)`
 * reads naturally, with `navigate.back()` available alongside it.
 */
export interface NavigateFn {
  (to: string, options?: { replace?: boolean }): void;
  back: () => void;
}

export function useNavigate(): NavigateFn {
  const { navigate, back } = useRouter();
  return useMemo(() => {
    const fn = ((to: string, options?: { replace?: boolean }) => navigate(to, options)) as NavigateFn;
    fn.back = back;
    return fn;
  }, [navigate, back]);
}

export function useParams<T extends RouteParams = RouteParams>(): Partial<T> {
  return useRouter().params as Partial<T>;
}

export function useLocation(): { pathname: string; search: string; hash: string } {
  const { pathname, search, hash } = useRouter();
  return { pathname, search, hash };
}

export function useSearchParams(): [
  URLSearchParams,
  (next: Record<string, string | null>, options?: { replace?: boolean }) => void,
] {
  const { searchParams, setSearchParams } = useRouter();
  return [searchParams, setSearchParams];
}

/** Renders whatever the route table matched for the current location. */
export function RouterOutlet() {
  const { element, fallback } = useRouter();
  return <>{element ?? fallback}</>;
}

/* -------------------------------------------------------------------------- */
/* Links                                                                      */
/* -------------------------------------------------------------------------- */

export interface LinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
  to: string;
  replace?: boolean;
  children: ReactNode;
}

function shouldIntercept(event: MouseEvent<HTMLAnchorElement>, target: string): boolean {
  if (event.defaultPrevented) return false;
  if (event.button !== 0) return false;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
  const anchorTarget = event.currentTarget.getAttribute('target');
  if (anchorTarget && anchorTarget !== '_self') return false;
  if (/^[a-z][a-z0-9+.-]*:/i.test(target) && !target.startsWith('/')) return false;
  return true;
}

export function Link({ to, replace, onClick, children, ...rest }: LinkProps) {
  const { navigate } = useRouter();
  return (
    <a
      {...rest}
      href={to}
      onClick={(event) => {
        onClick?.(event);
        if (shouldIntercept(event, to)) {
          event.preventDefault();
          navigate(to, { replace });
        }
      }}
    >
      {children}
    </a>
  );
}

export interface NavLinkProps extends LinkProps {
  /** Match the path exactly instead of by prefix. */
  end?: boolean;
}

export function NavLink({ to, end, ...rest }: NavLinkProps) {
  const { isActive } = useRouter();
  const active = isActive(to, { end });
  return <Link {...rest} to={to} aria-current={active ? 'page' : undefined} />;
}

/* -------------------------------------------------------------------------- */
/* Imperative navigation for non-component code                               */
/* -------------------------------------------------------------------------- */

export const router = {
  navigate: (to: string, options?: { replace?: boolean }): void =>
    pushHistory(to, options?.replace ?? false),
  back: (): void => window.history.back(),
  currentPath: (): string => snapshot.pathname,
};
