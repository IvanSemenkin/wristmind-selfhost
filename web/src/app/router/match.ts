/* =============================================================================
   Minimal path matching for the console router.

   Deliberately tiny and framework-free: the production WristMind frontend has
   its own navigation layer, so the route table must be easy to map onto
   whatever it uses.
   ========================================================================== */

export interface RouteParams {
  [key: string]: string;
}

/** Normalises `/chats/` → `/chats`, keeps `/` as `/`. */
export function normalizePath(path: string): string {
  if (!path) return '/';
  const [withoutQuery] = path.split(/[?#]/);
  const trimmed = withoutQuery.replace(/\/+$/, '');
  return trimmed === '' ? '/' : trimmed.startsWith('/') ? trimmed : `/${trimmed}`;
}

/**
 * Matches a pathname against a pattern such as `/chats/:chatId`.
 * Returns the captured params, or `null` when the pattern does not apply.
 */
export function matchPath(pattern: string, pathname: string): RouteParams | null {
  const patternParts = normalizePath(pattern).split('/').filter(Boolean);
  const pathParts = normalizePath(pathname).split('/').filter(Boolean);

  if (patternParts.length !== pathParts.length) return null;

  const params: RouteParams = {};
  for (let index = 0; index < patternParts.length; index += 1) {
    const segment = patternParts[index];
    const value = pathParts[index];

    if (segment.startsWith(':')) {
      if (value === '') return null;
      params[segment.slice(1)] = decodeURIComponent(value);
      continue;
    }
    if (segment !== value) return null;
  }

  return params;
}

export interface RouteDefinition<P extends RouteParams = RouteParams> {
  path: string;
  /** Path this route forwards to, e.g. `/` → `/main`. */
  redirect?: string;
  render?: (params: P) => unknown;
}

export interface RouteResolution {
  route: RouteDefinition | null;
  params: RouteParams;
  redirect: string | null;
}

export function resolveRoute(
  routes: RouteDefinition[],
  pathname: string,
): RouteResolution {
  for (const route of routes) {
    const params = matchPath(route.path, pathname);
    if (params) {
      return { route, params, redirect: route.redirect ?? null };
    }
  }
  return { route: null, params: {}, redirect: null };
}

/** Builds a concrete href from a pattern and params (used by typed links). */
export function buildPath(pattern: string, params: RouteParams): string {
  return normalizePath(
    pattern
      .split('/')
      .map((segment) =>
        segment.startsWith(':') ? encodeURIComponent(params[segment.slice(1)] ?? '') : segment,
      )
      .join('/'),
  );
}
