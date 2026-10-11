import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { parseAnswerChart } from './answerChart.ts';
test('chart accepts finite data, sorts x and preserves textual fallback', () => {
  assert.deepEqual(parseAnswerChart(JSON.stringify({title:'График',summary:'Растёт',points:[[2,4],[0,0]]}))?.points, [[0,0],[2,4]]);
});
test('partial, executable, oversized and degenerate chart data stays ordinary code', () => {
  for (const value of ['{', 'alert(1)', JSON.stringify({title:'x',summary:'x',points:[[0,1],[0,2]]}),
    JSON.stringify({title:'x',summary:'x',points:[[0,1],['2',3]]}),
    JSON.stringify({title:'x',summary:'x',points:Array.from({length:501},(_,i)=>[i,i])})]) assert.equal(parseAnswerChart(value), null);
});
import { chartTicks } from './answerChart.ts';
test('grid uses nice steps that get finer at higher zoom', () => {
  const wide = chartTicks(-3,3), zoomed = chartTicks(-1.5,1.5);
  assert.ok(wide.includes(0) && zoomed.includes(0));
  assert.ok(zoomed[1]-zoomed[0] < wide[1]-wide[0]);
  assert.ok(chartTicks(1e11,1e12).length <= 12);
  assert.ok(chartTicks(-.003,.003).every(Number.isFinite));
});
