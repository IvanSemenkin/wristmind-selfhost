const {test} = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const esbuild = Module.createRequire(require.resolve('vite'))('esbuild');
function load(file) {
  const built = esbuild.buildSync({entryPoints:[path.join(__dirname,file)], tsconfig:path.join(__dirname,'../../tsconfig.app.json'), bundle:true,write:false,platform:'node',format:'cjs'});
  const compiled = new Module(__filename);
  compiled._compile(built.outputFiles[0].text,__filename);
  return compiled.exports;
}
const {ApiWristMindService} = load('../services/ApiWristMindService.ts');
const {WristMindClientStore} = load('../store/clientStore.ts');
global.window = {setTimeout,clearTimeout,setInterval,clearInterval,addEventListener(){},removeEventListener(){}};
global.document = {visibilityState:'visible',addEventListener(){},removeEventListener(){}};
const defer = () => { let resolve; const promise = new Promise(r=>resolve=r); return {promise,resolve}; };
const json = value => new Response(JSON.stringify(value), {headers:{'Content-Type':'application/json'}});
const message = (id,content=id) => ({id,chat_id:'chat',role:'assistant',content,status:'complete',phases:[],sources:[]});
const input = {chat_id:'chat',content:'Question',client_message_id:'request'};
async function withFetch(fetcher, run) {
  const before = global.fetch; global.fetch = fetcher;
  try { await run(new ApiWristMindService({baseUrl:'https://example.test',token:'test'})); }
  finally { global.fetch = before; }
}
test('completion selects the exact answer even if a later turn already exists', async () => {
  await withFetch(async url => {
    if (url.endsWith('/events')) return new Response('event: complete\ndata: {"message_id":"current"}\n\n');
    if (url.endsWith('/messages')) return json([message('old'),message('current'),message('later')]);
    throw new Error(url);
  }, async service => {
    // Distinguish POST acceptance from the history GET.
    const fetcher=global.fetch;
    global.fetch = (url, options) => options?.method==='POST' ? Promise.resolve(json({id:'job'})) : fetcher(url,options);
    assert.equal((await service.chats.send(input)).id,'current');
  });
});
test('server errors cannot be replaced by the previous successful answer', async () => {
  await withFetch(async (_url, options) => options?.method==='POST' ? json({id:'job'}) : new Response('event: error\ndata: {"detail":"Provider failed"}\n\n'), async service => {
    let finals=0;
    await assert.rejects(service.chats.send(input,{onFinal(){finals++;}}), /Provider failed/);
    assert.equal(finals,0);
  });
});
test('a prematurely closed stream waits for the accepted job and never resends', async () => {
  let posts=0, polls=0;
  await withFetch(async (url,options) => {
    if(options?.method==='POST') {posts++; return json({id:'job'});}
    if(url.endsWith('/events')) return new Response('event: delta\ndata: {"text":"Partial"}\n\n');
    if(url.endsWith('/jobs/job')) return json(++polls===1 ? {status:'running',result:{}} : {status:'complete',result:{message_id:'current'}});
    return json([message('current')]);
  }, async service => {
    assert.equal((await service.chats.send(input)).id,'current');
    assert.equal(posts,1);
    assert.equal(polls,2);
  });
});
test('network failure after acceptance recovers the exact completed answer', async () => {
  let posts=0;
  await withFetch(async (url,options) => {
    if(options?.method==='POST') {posts++;return json({id:'job'});}
    if(url.endsWith('/events')) throw new TypeError('Network Error');
    if(url.endsWith('/jobs/job')) return json({status:'complete',result:{message_id:'current'}});
    return json([message('previous'),message('current')]);
  }, async service => {assert.equal((await service.chats.send(input)).id,'current');assert.equal(posts,1);});
});
test('accepted provider failure must not restore a sent draft', async () => {
  await withFetch(async (_url,options) => options?.method==='POST' ? json({id:'job'}) : new Response('event: error\ndata: {"detail":"Provider failed"}\n\n'),
    async service => assert.rejects(service.chats.send(input),error=>error.details?.messageAccepted===true && error.code==='server'));
});
test('rejected submission remains eligible for draft recovery', async () => {
  await withFetch(async()=>new Response('{"detail":"Unavailable"}',{status:400,headers:{'Content-Type':'application/json'}}),
    async service=>assert.rejects(service.chats.send(input),error=>!error.details?.messageAccepted));
});
test('returning to a visible tab recovers a stalled stream without cancelling the job', async () => {
  const browser=new EventTarget(),page=new EventTarget();page.visibilityState='visible';
  const oldWindow=global.window,oldDocument=global.document;
  global.window=Object.assign(browser,{setTimeout,clearTimeout,setInterval,clearInterval});global.document=page;
  const opened=defer();let cancels=0;
  try {
    await withFetch(async(url,options)=> {
      if(url.endsWith('/cancel')) {cancels++;return json({});}
      if(options?.method==='POST') return json({id:'job'});
      if(url.endsWith('/events')) return new Response(new ReadableStream({start(controller){
        options.signal.addEventListener('abort',()=>controller.error(new DOMException('Aborted','AbortError')),{once:true});opened.resolve();
      }}));
      if(url.endsWith('/jobs/job')) return json({status:'complete',result:{message_id:'current'}});
      return json([message('current')]);
    },async service=>{
      const result=service.chats.send(input);await opened.promise;
      page.dispatchEvent(new Event('visibilitychange'));
      assert.equal((await result).id,'current');assert.equal(cancels,0);
    });
  } finally {global.window=oldWindow;global.document=oldDocument;}
});
test('CRLF split across network chunks preserves all deltas and final id', async () => {
  await withFetch(async (url,options) => {
    if(options?.method==='POST') return json({id:'job'});
    if(url.endsWith('/events')) return new Response(new ReadableStream({start(controller){
      for(const part of ['event: delta\r','\ndata: {"text":"Hello"}\r','\n\r','\nevent: complete\r\ndata: {"message_id":"current"}\r\n\r\n']) controller.enqueue(new TextEncoder().encode(part));
      controller.close();
    }}));
    return json([message('current')]);
  }, async service => {
    let text='';
    assert.equal((await service.chats.send(input,{onDelta:(_id,delta)=>text+=delta})).id,'current');
    assert.equal(text,'Hello');
  });
});
test('Stop while acceptance is pending cancels the known job without opening SSE', async () => {
  const accepted=defer(); let cancels=0; const controller=new AbortController();
  await withFetch(async url => {
    if(url.endsWith('/cancel')) {cancels++; return json({status:'cancelled'});}
    if(url.endsWith('/messages')) return accepted.promise;
    throw new Error('Must not open stream');
  }, async service => {
    const result=service.chats.send({...input,signal:controller.signal});
    controller.abort(); accepted.resolve(json({id:'job'}));
    await assert.rejects(result,error=>error.code==='aborted');
    assert.equal(cancels,1);
  });
});
test('Stop during streaming releases transport and requests server cancellation', async () => {
  const opened=defer(); const controller=new AbortController(); let cancels=0;
  await withFetch(async (url,options) => {
    if(url.endsWith('/cancel')) {cancels++;return json({status:'cancelled'});}
    if(options?.method==='POST') return json({id:'job'});
    const body=new ReadableStream({start(stream){
      options.signal.addEventListener('abort',()=>stream.error(new DOMException('Aborted','AbortError')),{once:true});
    }});
    opened.resolve(); return new Response(body);
  }, async service => {
    const result=service.chats.send({...input,signal:controller.signal});
    await opened.promise; controller.abort();
    await assert.rejects(result,error=>error.code==='aborted');
    assert.equal(cancels,1);
  });
});
async function storeFor(messages) {
  const service={bootstrap:async()=>({modes:[],chats:[{id:'chat'}],sources:[],devices:[],pairingCodes:[],models:[],settings:null,stats:null,health:null}),subscribe:()=>()=>{},subscribeAccountEvents:()=>()=>{},chats:{messages,list:async()=>[{id:'chat'}]}};
  const store=new WristMindClientStore(service,{}); await store.bootstrap(); return {store,service};
}
test('failed history stays retryable instead of caching an empty conversation', async () => {
  let calls=0;
  const {store}=await storeFor(async()=> {if(++calls===1) throw new Error('Offline');return [message('old')];});
  try {await store.loadMessages('chat'); assert.equal(store.getSnapshot().messages.chat,undefined);
    await store.loadMessages('chat'); assert.equal(store.getSnapshot().messages.chat[0].id,'old');}
  finally {store.dispose();}
});
test('duplicate history loads share one network request', async () => {
  const pending=defer(); let calls=0;
  const {store}=await storeFor(()=>{calls++;return pending.promise;});
  try {const a=store.loadMessages('chat');const b=store.loadMessages('chat');pending.resolve([message('old')]);await Promise.all([a,b]);assert.equal(calls,1);}
  finally {store.dispose();}
});
test('late history cannot erase a completed local turn', async () => {
  const pending=defer(); const {store,service}=await storeFor(()=>pending.promise);
  service.chats.send=async (_input,handlers)=>{handlers.onFinal(message('new'));return message('new');};
  try {const loading=store.loadMessages('chat');await store.sendMessage(input);pending.resolve([message('old')]);await loading;
    assert.ok(store.getSnapshot().messages.chat.some(item=>item.id==='new'));}
  finally {store.dispose();}
});
test('deleted chat cannot be restored by an in-flight history request', async () => {
  const pending=defer(); const {store,service}=await storeFor(()=>pending.promise);service.chats.remove=async()=>{};
  try {const loading=store.loadMessages('chat');await store.deleteChat('chat');pending.resolve([message('old')]);await loading;assert.equal(store.getSnapshot().messages.chat,undefined);}
  finally {store.dispose();}
});
test('double submission does not start a second turn in the same chat', async () => {
  const pending=defer(); const {store,service}=await storeFor(async()=>[]);let sends=0;
  service.chats.send=()=>{sends++;return pending.promise;};
  try {const first=store.sendMessage(input);await assert.rejects(store.sendMessage(input),error=>error.code==='conflict');assert.equal(sends,1);pending.resolve(message('new'));await first;}
  finally {store.dispose();}
});
test('Stop during recovery cancels the accepted job once and cleans up polling', async () => {
  const controller=new AbortController();let cancels=0;
  await withFetch(async(url,options)=>{
    if(url.endsWith('/cancel')) {cancels++;return json({status:'cancelled'});}
    if(options?.method==='POST') return json({id:'job'});
    if(url.endsWith('/events')) throw new TypeError('Offline');
    queueMicrotask(()=>controller.abort());return json({status:'running',result:{}});
  },async service=>{
    await assert.rejects(service.chats.send({...input,signal:controller.signal}),error=>error.code==='aborted');
    assert.equal(cancels,1);
  });
});
