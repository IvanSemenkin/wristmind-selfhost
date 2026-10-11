const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const esbuild = Module.createRequire(require.resolve('vite'))('esbuild');

// Exercise the actual store, including its SSE debounce and final callback.
const built = esbuild.buildSync({
  entryPoints: [path.join(__dirname, '../store/clientStore.ts')],
  tsconfig: path.join(__dirname, '../../tsconfig.app.json'),
  bundle: true, write: false, platform: 'node', format: 'cjs',
});
const compiled = new Module(__filename);
compiled._compile(built.outputFiles[0].text, __filename);
const { WristMindClientStore } = compiled.exports;

global.window = { setTimeout, clearTimeout, setInterval, clearInterval,
  addEventListener() {}, removeEventListener() {} };
global.document = { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} };

for (const mode of ['remote-answer', 'local-answer', 'source-event']) {
  test(`five sources become ten without reloading (${mode})`, async () => {
    let sourceCount = 5;
    let feed;
    let sourceCalls = 0;
    const message = { id: 'answer', chat_id: 'chat', role: 'assistant', status: 'complete',
      content: 'Ответ', phases: [], web_sources: [] };
    const service = {
      bootstrap: async () => ({ modes: [], chats: [{id: 'chat', mode_id: null}], sources: [],
        devices: [], pairingCodes: [], models: [], settings: null, stats: null, health: null }),
      subscribe: () => () => {},
      subscribeAccountEvents: (_cursor, handlers) => { feed = handlers; return () => {}; },
      chats: {
        list: async () => [{id: 'chat', mode_id: null}],
        messages: async () => [message],
        sources: async () => { sourceCalls++; return {working: [], referenced: Array.from({length: sourceCount},
          (_, index) => ({id: `r${index}`, title: `${index}`, url: `https://example.test/${index}`}))}; },
      },
      knowledge: {list: async () => []},
    };
    const store = new WristMindClientStore(service, {});
    await store.bootstrap();
    await store.loadMessages('chat');
    let displayed = await service.chats.sources('chat');
    let lastRevision = store.getSnapshot().chatSourcesRevision;
    const unsubscribe = store.subscribe(() => {
      const revision = store.getSnapshot().chatSourcesRevision;
      if (revision === lastRevision) return;
      lastRevision = revision;
      void service.chats.sources('chat').then(value => { displayed = value; });
    });
    try {
      assert.equal(displayed.referenced.length, 5);
      if (mode === 'local-answer') {
        service.chats.send = async (_input, handlers) => {
          const before = store.getSnapshot().chatSourcesRevision;
          handlers.onPhase('', 'generating');
          handlers.onDelta('', 'Токен');
          assert.equal(store.getSnapshot().chatSourcesRevision, before);
          assert.equal(sourceCalls, 1, 'streamed tokens must not refetch sources');
          sourceCount = 10;
          handlers.onFinal(message);
          return message;
        };
        await store.sendMessage({chat_id: 'chat', content: 'Ещё вопрос'});
      } else {
        sourceCount = 10;
        // This answer already has the same id, status and message count.
        feed.onEvent({id: 1, type: mode === 'remote-answer' ? 'message.updated' : 'source.updated',
          data: {chat_id: 'chat'}});
        await new Promise(resolve => setTimeout(resolve, 220));
        assert.equal(store.getSnapshot().messages.chat.length, 1);
        assert.equal(store.getSnapshot().messages.chat[0].status, 'complete');
      }
      await Promise.resolve();
      assert.equal(displayed.referenced.length, 10);
    } finally {
      unsubscribe();
      store.dispose();
    }
  });
}
