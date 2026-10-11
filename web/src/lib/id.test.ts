import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequestId } from './id.ts';
test('HTTP request UUIDs do not require the secure-context randomUUID API', () => {
  const original=Object.getOwnPropertyDescriptor(globalThis,'crypto');
  const crypto=globalThis.crypto;
  Object.defineProperty(globalThis,'crypto',{configurable:true,value:{getRandomValues:crypto.getRandomValues.bind(crypto)}});
  try {
    const ids=new Set(Array.from({length:1000},()=>createRequestId()));
    assert.equal(ids.size,1000);
    for(const id of ids) assert.match(id,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  } finally {if(original)Object.defineProperty(globalThis,'crypto',original);}
});
