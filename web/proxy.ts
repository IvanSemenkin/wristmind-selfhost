import { NextResponse, type NextRequest } from 'next/server';

const contentTypes: Record<string, string> = {
  '/.well-known/assetlinks.json': 'application/json; charset=utf-8',
  '/manifest.webmanifest': 'application/manifest+json; charset=utf-8',
  '/favicon.svg': 'image/svg+xml',
  '/wristmind-mark.svg': 'image/svg+xml',
};

export function proxy(request: NextRequest) {
  const response = NextResponse.next();
  const contentType = contentTypes[request.nextUrl.pathname];
  if (contentType) response.headers.set('Content-Type', contentType);
  return response;
}

export const config = {
  matcher: [
    '/.well-known/assetlinks.json',
    '/manifest.webmanifest',
    '/favicon.svg',
    '/wristmind-mark.svg',
  ],
};
