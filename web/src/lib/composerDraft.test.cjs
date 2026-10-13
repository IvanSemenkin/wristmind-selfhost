const {test}=require('node:test');
const assert=require('node:assert/strict');
const Module=require('node:module');
const path=require('node:path');
const esbuild=Module.createRequire(require.resolve('vite'))('esbuild');
function mount(onSend) {
  const values=[];
  const hooks={useState(initial){const index=values.length;values.push(typeof initial==='function'?initial():initial);return [values[index],next=>values[index]=typeof next==='function'?next(values[index]):next];},useRef:initial=>({current:initial}),useEffect(){}};
  const built=esbuild.buildSync({entryPoints:[path.join(__dirname,'../pages/chats/Composer.tsx')],bundle:true,write:false,platform:'node',format:'cjs',external:['react','react/jsx-runtime','lucide-react','*.css'],tsconfig:path.join(__dirname,'../../tsconfig.app.json')});
  const compiled=new Module(__filename);
  const original=Module.createRequire(__filename);
  compiled.require=name=>name==='react'?{...original('react'),...hooks}:name.endsWith('.css')?{}:original(name);
  compiled._compile(built.outputFiles[0].text,__filename);
  const tree=compiled.exports.Composer({draftKey:'chat',onSend,streaming:false,researchMode:false,onResearchModeToggle(){}});
  function find(node){if(!node||typeof node!=='object')return;if(node.props?.['aria-label']==='Отправить сообщение')return node;for(const child of [node.props?.children].flat(Infinity)){const found=find(child);if(found)return found;}}
  return {send:()=>find(tree).props.onClick(),values};
}
async function withBrowser(run){
  const previous={window:global.window,sessionStorage:global.sessionStorage,requestAnimationFrame:global.requestAnimationFrame};
  const storage=new Map([['wristmind.draft.chat','Question']]);
  global.sessionStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
  global.window={matchMedia:()=>({matches:true})};global.requestAnimationFrame=callback=>callback();
  try{await run(storage);}finally{Object.assign(global,previous);}
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('sending clears persistent draft synchronously before navigation unmounts the composer',async()=>withBrowser(async storage=>{
  const composer=mount(async()=>{});composer.send();
  assert.equal(storage.has('wristmind.draft.chat'),false);
  await settle();assert.equal(composer.values[0],'');
}));
test('rejected submission restores the editable draft',async()=>withBrowser(async()=>{
  const composer=mount(async()=>false);composer.send();await settle();assert.equal(composer.values[0],'Question');
}));
