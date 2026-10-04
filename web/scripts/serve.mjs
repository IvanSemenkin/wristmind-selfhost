import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import { Readable } from "node:stream";
import { fileURLToPath } from "node:url";
import { dirname, extname, normalize, resolve, sep } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const outputRoot = resolve(here, "..", "dist");
const assetsRoot = resolve(outputRoot, "client");
const worker = await import(resolve(outputRoot, "server", "index.js"));
const host = process.env.HOST ?? "127.0.0.1";
const port = Number(process.env.PORT ?? 18786);

function assetPath(pathname) {
  const decoded = decodeURIComponent(pathname);
  const candidate = resolve(assetsRoot, `.${normalize(decoded)}`);
  return candidate === assetsRoot || candidate.startsWith(`${assetsRoot}${sep}`) ? candidate : null;
}

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".ico": "image/x-icon",
};

const assets = {
  async fetch(request) {
    const path = assetPath(new URL(request.url).pathname);
    if (!path || !existsSync(path)) return new Response("Not found", { status: 404 });
    return new Response(Readable.toWeb(createReadStream(path)));
  },
};

createServer(async (request, response) => {
  try {
    const origin = `http://${request.headers.host ?? `${host}:${port}`}`;
    const url = new URL(request.url ?? "/", origin);
    const staticPath = assetPath(url.pathname);
    if (url.pathname.startsWith("/_next/static/") && staticPath && existsSync(staticPath)) {
      response.writeHead(200, {
        "content-type": contentTypes[extname(staticPath)] ?? "application/octet-stream",
        "cache-control": "public, max-age=31536000, immutable",
      });
      return createReadStream(staticPath).pipe(response);
    }
    const body = request.method === "GET" || request.method === "HEAD" ? undefined : request;
    const appRequest = new Request(url, {
      method: request.method,
      headers: request.headers,
      body,
      duplex: body ? "half" : undefined,
    });
    const appResponse = await worker.default.fetch(appRequest, { ASSETS: assets });
    response.writeHead(appResponse.status, Object.fromEntries(appResponse.headers));
    if (!appResponse.body) return response.end();
    Readable.fromWeb(appResponse.body).pipe(response);
  } catch (error) {
    console.error("WristMind web request failed", error);
    response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    response.end("Internal server error");
  }
}).listen(port, host, () => console.log(`WristMind panel is listening on http://${host}:${port}`));
