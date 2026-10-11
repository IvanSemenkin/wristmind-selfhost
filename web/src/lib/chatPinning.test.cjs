const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const esbuild = Module.createRequire(require.resolve('vite'))('esbuild');
const built = esbuild.buildSync({entryPoints:[path.join(__dirname,'../services/ApiWristMindService.ts')],
  tsconfig:path.join(__dirname,'../../tsconfig.app.json'),bundle:true,write:false,platform:'node',format:'cjs'});
const compiled = new Module(__filename);
compiled._compile(built.outputFiles[0].text,__filename);
const { ApiWristMindService } = compiled.exports;

test('pin patch keeps the title and persisted flag after reload and rename', async () => {
  const originalFetch = global.fetch;
  let chat = {id:'chat', title:'Моя задача', pinned:false};
  let patch;
  global.fetch = async (_url, options = {}) => {
    if (options.method === 'PATCH') {
      patch = JSON.parse(options.body);
      chat = {...chat, ...patch};
    }
    return new Response(JSON.stringify(options.method === 'PATCH' ? chat : [chat]), {
      status:200,headers:{'Content-Type':'application/json'},
    });
  };
  try {
    const service = new ApiWristMindService({baseUrl:'https://example.test',token:'test-token'});
    const result = await service.chats.update('chat',{pinned:true});
    assert.deepEqual(patch,{pinned:true});
    assert.equal(result.title,'Моя задача');
    assert.equal(result.pinned,true);
    assert.equal((await service.chats.list())[0].pinned,true);
    assert.equal((await service.chats.update('chat',{title:'Новое'})).pinned,true);
    assert.equal((await service.chats.update('chat',{pinned:false})).title,'Новое');
  } finally { global.fetch = originalFetch; }
});
