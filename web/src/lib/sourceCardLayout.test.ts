import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

/* =============================================================================
   Source-card layout contract.

   There is no browser test runner in this package, so the rules that actually
   prevent the reported overflow are asserted directly. A source card is a flex
   row (monogram · text column · action icon), and text can only shrink inside
   it when the text elements carry `min-width: 0`. Dropping that — or adding
   `white-space: nowrap` without a truncation pair — is exactly how a long
   origin title escapes the card again.
   ========================================================================== */

const CARD_CSS = fileURLToPath(
  new URL('../pages/chats/MessageSources.module.css', import.meta.url),
);
const css = readFileSync(CARD_CSS, 'utf8');

/** The first declaration block of a class, without crossing into a media query. */
function declarations(selector: string): string {
  const match = css.match(new RegExp(`\\.${selector}\\s*\\{([^}]*)\\}`));
  assert.ok(match, `.${selector} rule is missing from the card stylesheet`);
  return match[1];
}

function expects(selector: string, ...needles: string[]): void {
  const body = declarations(selector);
  for (const needle of needles) {
    assert.ok(body.includes(needle), `.${selector} must declare ${needle}`);
  }
}

test('the card row can shrink instead of pushing its text out', () => {
  expects('card', 'min-width: 0', 'max-width: 100%');
  expects('cardBody', 'min-width: 0', 'overflow: hidden');
});

test('the title is limited to two lines', () => {
  const body = declarations('cardTitle');
  assert.match(body, /-webkit-line-clamp:\s*2/);
  assert.match(body, /overflow:\s*hidden/);
  // Long words and URLs still have to break inside the clamp.
  assert.match(body, /overflow-wrap:\s*anywhere/);
});

test('nowrap meta text always comes with a truncation pair', () => {
  for (const selector of ['cardPage', 'cardDomain']) {
    const body = declarations(selector);
    assert.match(body, /white-space:\s*nowrap/);
    assert.match(body, /min-width:\s*0/);
    assert.match(body, /overflow:\s*hidden/);
    assert.match(body, /text-overflow:\s*ellipsis/);
    assert.match(body, /max-width:\s*100%/);
  }
});

test('the meta row wraps and cannot overflow its column', () => {
  const body = declarations('cardMeta');
  assert.match(body, /flex-wrap:\s*wrap/);
  assert.match(body, /min-width:\s*0/);
});

test('the snippet is clamped and breaks unbroken strings', () => {
  const body = declarations('cardSnippet');
  assert.match(body, /-webkit-line-clamp:\s*\d/);
  assert.match(body, /overflow-wrap:\s*anywhere/);
});
