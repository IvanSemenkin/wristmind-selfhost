import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {compileExpression} from './mathExpression.ts';
import {chartCurves,chartIntersections,curveValue,initialViewport,panViewport,sampleCurve,zoomViewport} from './chartGeometry.ts';
import {extractLooseChart,parseAnswerChart} from './answerChart.ts';
test('unfenced chart recovery preserves prose and quoted braces, hides incomplete envelope, leaves ordinary JSON alone',()=>{
  const raw=JSON.stringify({title:'График } "пример"',summary:'{текст}',points:[[-1,-1],[1,1]]});
  assert.deepEqual(extractLooseChart(raw+'\nОтвет: готово.'),{value:raw,tail:'\nОтвет: готово.'});
  assert.ok(parseAnswerChart(extractLooseChart(raw)!.value));
  const partial=raw.slice(0,-6);
  assert.deepEqual(extractLooseChart(partial),{value:partial,tail:''});
  for(const ordinary of ['{"title":"Книга","summary":"Обзор"}','```chart\n'+raw+'\n```','Обычный ответ '+raw]) assert.equal(extractLooseChart(ordinary),null);
});
const chart=(expressions:string[])=>parseAnswerChart(JSON.stringify({title:'Графики',summary:'Пример',points:[[-5,0],[5,0]],functions:expressions.map(expression=>({expression}))}))!;
test('safe arithmetic: precedence, powers, implicit products, constants and requested functions',()=>{
  for(const [expression,x,y] of [['2x+1',2,5],['x²',3,9],['1/x',2,.5],['sin(x)',Math.PI/2,1],['tan(x)',0,0],['√(x)',4,2],['√x',4,2],['-x^2',2,-4],['2^3^2',0,512],['cos(pi)',0,-1]] as const) assert.ok(Math.abs(compileExpression(expression).evaluate(x)-y)<1e-10,expression);
  assert.ok(Number.isNaN(compileExpression('sqrt(x)').evaluate(-1)));
  assert.ok(Number.isNaN(compileExpression('1/x').evaluate(0)));
  assert.ok(Number.isNaN(compileExpression('1e308*x').evaluate(10)));
  assert.equal(compileExpression('2x+1').tex,'y=2x+1');
  for(const expression of ['eval(x)','window.x','x.constructor','alert(1)','sin x','x;1','__proto__(x)','x=2','('.repeat(40)+'x'+')'.repeat(40),'x'.repeat(301)]) assert.throws(()=>compileExpression(expression),expression);
});
test('viewport-anchored zoom, pan and reset bounds are finite',()=>{
  const data=chart(['x^2']),curves=chartCurves(data),v=initialViewport(data,curves);
  assert.ok(v.minY<0&&v.maxY>20);
  const z=zoomViewport(v,.5,.25,.75);
  assert.equal(z.minX+(z.maxX-z.minX)*.25,v.minX+(v.maxX-v.minX)*.25);
  assert.equal(z.maxY-(z.maxY-z.minY)*.75,v.maxY-(v.maxY-v.minY)*.75);
  const p=panViewport(z,.1,.2);assert.equal(p.maxX-p.minX,z.maxX-z.minX);
  assert.ok(Object.values(zoomViewport(v,1e50)).every(Number.isFinite));
  const extreme=zoomViewport({minX:1e12-5,maxX:1e12,minY:-5,maxY:5},1e-100);
  assert.ok(extreme.maxX>extreme.minX && extreme.maxY>extreme.minY);
});
test('curves resample beyond original points and several functions stay independent',()=>{
  const curves=chartCurves(chart(['2*x+1','x^2','sin(x)']));
  const v={minX:10,maxX:20,minY:-2,maxY:500};
  for(const c of curves){const segments=sampleCurve(c,v,500);assert.equal(segments[0][0][0],10);assert.equal(segments.at(-1)!.at(-1)![0],20);}
  assert.equal(curveValue(curves[0],20),41);assert.equal(curveValue(curves[1],20),400);
});
test('reciprocal and tangent never bridge poles, including translated poles and zoomed views',()=>{
  for(const [expression,poles] of [['1/x',[0]],['1/(x-0.123)',[.123]],['tan(x)',[-Math.PI/2,Math.PI/2]]] as [string,number[]][]){
    const c=chartCurves(chart([expression]))[0];
    for(const width of [200,553,1000]) for(const v of [{minX:-5,maxX:5,minY:-5,maxY:5},{minX:-2,maxX:2,minY:-20,maxY:20}]){
      const segments=sampleCurve(c,v,width);
      assert.ok(segments.length>=2,expression);
      for(const s of segments)for(const pole of poles)assert.ok(!(s[0][0]<pole&&s.at(-1)![0]>pole),expression);
      assert.ok(segments.flat().every(p=>p.every(Number.isFinite)));
    }
  }
});
test('square root and declared domains omit undefined regions',()=>{
  const c=chartCurves(chart(['sqrt(x)']))[0];
  const segments=sampleCurve(c,{minX:-5,maxX:5,minY:-1,maxY:5},400);
  assert.ok(segments.flat().every(p=>p[0]>=0));
  c.domain=[1,3];assert.ok(Number.isNaN(curveValue(c,0)));
  assert.ok(sampleCurve(c,{minX:-5,maxX:5,minY:-1,maxY:5},400).flat().every(p=>p[0]>=1&&p[0]<=3));
});
test('legacy points stay bounded and duplicate abscissas separate branches',()=>{
  const c=chartCurves({title:'Данные',summary:'',points:[[-1,1],[0,2],[0,3],[1,4]]})[0];
  assert.ok(Number.isNaN(curveValue(c,2)));
  assert.equal(sampleCurve(c,{minX:-5,maxX:5,minY:-1,maxY:5},400).length,2);
});
test('invalid expression or domain rejects the whole chart, not a misleading legacy fallback',()=>{
  assert.equal(chart(['window.alert(x)']),null);
  for(const domain of [[3,1],['0',5],[0,1e20]])assert.equal(parseAnswerChart(JSON.stringify({title:'x',summary:'',points:[[0,0],[1,1]],functions:[{expression:'x',domain}]})),null);
});

test('explicit legacy equation is recovered only when all points agree',()=>{
  const straight=chartCurves({title:'Прямая y=2x+1',summary:'',points:[[-5,-9],[0,1],[5,11]]})[0];
  assert.equal(curveValue(straight,20),41);
  assert.ok(sampleCurve(straight,{minX:-50,maxX:50,minY:-100,maxY:100},500)[0].at(-1)![0]===50);
  const parabola=chartCurves({title:'Парабола y=x² на [-5, 5]',summary:'',points:[[-5,25],[0,0],[5,25]]})[0];
  assert.equal(curveValue(parabola,10),100);
  for(const title of ['Измерения','Прямая y=alert(x)','Прямая y=2x+1']) {
    const data=chartCurves({title,summary:'',points:[[0,3],[1,4]]})[0];
    assert.ok(Number.isNaN(curveValue(data,20)));
  }
});

test('snap intersections include axes and other visible curves, not poles or hidden functions',()=>{
  const v={minX:-5,maxX:5,minY:-20,maxY:30};
  const linear=chartIntersections(chartCurves(chart(['2*x+1'])),v);
  assert.ok(linear.some(p=>p.kind==='y-axis'&&p.x===0&&p.y===1));
  assert.ok(linear.some(p=>p.kind==='x-axis'&&Math.abs(p.x+.5)<1e-9&&p.y===0));
  const pair=chartIntersections(chartCurves(chart(['x','-x+2'])),v);
  assert.ok(pair.some(p=>p.kind==='curves'&&Math.abs(p.x-1)<1e-9&&Math.abs(p.y-1)<1e-9));
  assert.ok(!chartIntersections(chartCurves(chart(['x','-x+2'])),v,[1]).some(p=>p.kind==='curves'));
  assert.ok(!chartIntersections(chartCurves(chart(['x','x'])),v).some(p=>p.kind==='curves'));
  assert.ok(!chartIntersections(chartCurves(chart(['1/x','tan(x)'])),v).some(p=>p.kind==='x-axis'&&p.curve===0));
});
