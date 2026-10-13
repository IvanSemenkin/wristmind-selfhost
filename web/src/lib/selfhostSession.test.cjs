const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const Module=require('node:module');
const esbuild=Module.createRequire(require.resolve('vite'))('esbuild');
const built=esbuild.buildSync({entryPoints:[path.join(__dirname,'../services/ApiWristMindService.ts')],tsconfig:path.join(__dirname,'../../tsconfig.app.json'),bundle:true,write:false,platform:'node',format:'cjs'});
const compiled=new Module(__filename);compiled._compile(built.outputFiles[0].text,__filename);
const {ApiWristMindService}=compiled.exports;
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
async function check(detail,sessionResponse,expectedCalls) {
  const before=global.fetch;let invalid=0,checks=0;
  global.fetch=async url=>{
    if(url.endsWith('/selfhost/session')) {checks++;if(sessionResponse instanceof Error) throw sessionResponse;return sessionResponse;}
    return json({detail},401);
  };
  try {
    const service=new ApiWristMindService({baseUrl:'https://example.test',token:'',deviceId:'panel'},()=>invalid++);
    await assert.rejects(service.devices.list());
    assert.equal(invalid,expectedCalls);
    return checks;
  } finally {global.fetch=before;}
}
test('late unauthorized response cannot discard the current valid cookie session',async()=>{
  assert.equal(await check('Invalid device token',json({deviceId:'same-panel'}),0),1);
});
test('confirmed invalid cookie session prompts login',async()=>{
  assert.equal(await check('Device token required',json({detail:'Device token required'},401),1),1);
});
test('network failure while checking authentication does not log the user out',async()=>{
  await check('Invalid device token',new TypeError('Offline'),0);
});
test('provider authorization failures cannot log the user out of the panel',async()=>{
  assert.equal(await check('Provider key rejected',json({},401),0),0);
});
