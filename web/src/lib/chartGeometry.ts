import { compileExpression, type MathFunction } from './mathExpression.ts';
import type { AnswerChart } from './answerChart.ts';
export type Point = [number, number];
export type Viewport = { minX: number; maxX: number; minY: number; maxY: number };
export type Curve = { label: string; math?: MathFunction; domain?: Point; points?: Point[] };
export function chartCurves(chart: AnswerChart): Curve[] {
  if (chart.functions) return chart.functions.map(f => ({label:f.label,math:compileExpression(f.expression),domain:f.domain}));
  // Older model answers often put an explicit equation in the title. Recover
  // only that declared equation, and only when every supplied point agrees.
  // Never fit or extrapolate arbitrary measurement data.
  const declared=chart.title.match(/\by\s*=\s*(.+)$/i)?.[1].split(/\s+на\s+/iu)[0].replace(/\.$/,'');
  if(declared) {
    try {
      const math=compileExpression(declared);
      const agrees=chart.points.every(([x,y])=>{const actual=math.evaluate(x);return Number.isFinite(actual)&&Math.abs(actual-y)<=1e-6*Math.max(1,Math.abs(y));});
      if(agrees)return [{label:chart.title,math}];
    } catch { /* A non-arithmetic title remains an ordinary data chart. */ }
  }
  return [{label:chart.title,points:chart.points}];
}
export function curveValue(curve: Curve, x: number): number {
  if (curve.domain && (x < curve.domain[0] || x > curve.domain[1])) return NaN;
  if (curve.math) return curve.math.evaluate(x);
  const points = curve.points!;
  if (x < points[0][0] || x > points.at(-1)![0]) return NaN;
  let low = 0, high = points.length-1;
  while (high-low > 1) { const mid = (low+high)>>1; if (points[mid][0] <= x) low = mid; else high = mid; }
  const a=points[low],b=points[high];
  return a[0] === b[0] ? a[1] : a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0]);
}
export function initialViewport(chart: AnswerChart, curves: Curve[]): Viewport {
  let minX=chart.points[0][0],maxX=chart.points.at(-1)![0];
  if (curves.every(c=>c.math)) {
    const xs=Array.from({length:201},(_,i)=>minX+(maxX-minX)*i/200).filter(x=>curves.some(c=>Number.isFinite(curveValue(c,x))));
    if(xs.length>1){minX=xs[0];maxX=xs.at(-1)!;}
  }
  const values = curves.flatMap(c => c.math ? Array.from({length:201},(_,i)=>curveValue(c,minX+(maxX-minX)*i/200)) : c.points!.map(p=>p[1]))
    .filter(Number.isFinite).sort((a,b)=>a-b);
  const trim=curves.some(c=>c.math) ? .02 : 0;
  const low=values[Math.floor(values.length*trim)] ?? -5,high=values[Math.floor((values.length-1)*(1-trim))] ?? 5;
  const span=Math.max(high-low,Math.abs(low)*.1,2),pad=span*.1;
  return {minX,maxX,minY:low-pad,maxY:high+pad};
}
/** Zoom anchored to a normalized cursor position, with bounded numerical range. */
export function zoomViewport(v: Viewport, factor: number, px=.5, py=.5): Viewport {
  const sx=v.maxX-v.minX,sy=v.maxY-v.minY;
  const x=v.minX+sx*px,y=v.maxY-sy*py;
  const precision=Math.max(1e-7,Math.abs(x)*Number.EPSILON*16,Math.abs(y)*Number.EPSILON*16);
  const f=Math.max(precision/Math.min(sx,sy),Math.min(1e10/Math.max(sx,sy),factor));
  return {minX:x-sx*f*px,maxX:x+sx*f*(1-px),minY:y-sy*f*(1-py),maxY:y+sy*f*py};
}
export function panViewport(v: Viewport, dx: number, dy: number): Viewport {
  const x=dx*(v.maxX-v.minX),y=dy*(v.maxY-v.minY);
  if (Math.max(Math.abs(v.minX-x),Math.abs(v.maxX-x),Math.abs(v.minY+y),Math.abs(v.maxY+y)) > 1e12) return v;
  return {minX:v.minX-x,maxX:v.maxX-x,minY:v.minY+y,maxY:v.maxY+y};
}
/** Screen-density sampling, midpoint refinement, and denominator/pole barriers. */
export function sampleCurve(curve: Curve, v: Viewport, pixels: number): Point[][] {
  if (curve.points) {
    // Original data is bounded; repeated x coordinates are explicit breaks.
    const segments: Point[][]=[]; let line: Point[]=[];
    for (const p of curve.points) { if (line.length && p[0] === line.at(-1)![0]) { segments.push(line); line=[]; } line.push(p); }
    if (line.length) segments.push(line);
    return segments;
  }
  const count=Math.max(120,Math.min(1000,Math.round(pixels))),segments:Point[][]=[];
  let line:Point[]=[];
  const ySpan=v.maxY-v.minY;
  const read=(x:number):Point=>[x,curveValue(curve,x)];
  const connected=(a:Point,b:Point,m:Point):boolean=> {
    if (![a[1],b[1],m[1]].every(Number.isFinite)) return false;
    const aa=curve.math!.barriers(a[0]),bb=curve.math!.barriers(b[0]),mm=curve.math!.barriers(m[0]);
    if (aa.some((n,i)=>!Number.isFinite(n) || n === 0 || n*bb[i] <= 0 || n*mm[i] <= 0)) return false;
    return !(Math.abs(m[1]-(a[1]+b[1])/2)>ySpan*2 && Math.abs(a[1]-b[1])>ySpan);
  };
  const append=(a:Point,b:Point,depth:number)=> {
    const m=read((a[0]+b[0])/2);
    if (!connected(a,b,m)) { if (line.length) segments.push(line); line=[]; return; }
    if (depth<4 && Math.abs(m[1]-(a[1]+b[1])/2)>ySpan/Math.max(100,pixels)) {
      append(a,m,depth+1); append(m,b,depth+1); return;
    }
    if (!line.length) line.push(a);
    line.push(b);
  };
  let a=read(v.minX);
  for (let i=1;i<=count;i++) { const b=read(v.minX+(v.maxX-v.minX)*i/count); append(a,b,0); a=b; }
  if (line.length) segments.push(line);
  return segments;
}

export type ChartIntersection={x:number;y:number;curve:number;kind:'x-axis'|'y-axis'|'curves'};
/** Visible intersections only, found numerically without crossing undefined branches. */
export function chartIntersections(curves:Curve[],v:Viewport,hidden:number[]=[]):ChartIntersection[] {
  const result:ChartIntersection[]=[],count=300;
  const xSpan=v.maxX-v.minX,ySpan=v.maxY-v.minY;
  const add=(x:number,y:number,curve:number,kind:ChartIntersection['kind'])=>{
    if(!Number.isFinite(y)||x<v.minX||x>v.maxX||y<v.minY||y>v.maxY)return;
    if(result.some(p=>p.curve===curve&&Math.abs(p.x-x)<xSpan*1e-7&&Math.abs(p.y-y)<ySpan*1e-7))return;
    result.push({x:Math.abs(x)<xSpan*1e-12?0:x,y:Math.abs(y)<ySpan*1e-12?0:y,curve,kind});
  };
  const continuous=(c:Curve,a:number,b:number)=>{
    if(!c.math)return true;
    const aa=c.math.barriers(a),bb=c.math.barriers(b);
    return !aa.some((n,i)=>!Number.isFinite(n)||!Number.isFinite(bb[i])||n*bb[i]<=0);
  };
  const roots=(a:Curve,b?:Curve):number[]=>{
    const value=(x:number)=>curveValue(a,x)-(b?curveValue(b,x):0);
    const found:number[]=[];
    let left=v.minX,fl=value(left);
    for(let i=1;i<=count;i++) {
      const right=v.minX+xSpan*i/count,fr=value(right);
      if(fl===0&&fr!==0)found.push(left);
      if(fr===0&&fl!==0)found.push(right);
      if(Number.isFinite(fl)&&Number.isFinite(fr)&&fl*fr<0&&continuous(a,left,right)&&(!b||continuous(b,left,right))) {
        let lo=left,hi=right,flo=fl;
        for(let step=0;step<42;step++) {const mid=(lo+hi)/2,fm=value(mid);if(!Number.isFinite(fm))break;if(flo*fm<=0)hi=mid;else{lo=mid;flo=fm;}}
        const x=(lo+hi)/2;
        if(Math.abs(value(x))<=Math.max(1e-8,ySpan*1e-8))found.push(x);
      }
      left=right;fl=fr;
    }
    return found;
  };
  curves.forEach((a,i)=>{
    if(hidden.includes(i))return;
    if(v.minX<=0&&v.maxX>=0)add(0,curveValue(a,0),i,'y-axis');
    if(v.minY<=0&&v.maxY>=0)for(const x of roots(a))add(x,0,i,'x-axis');
    curves.forEach((b,j)=>{if(j<=i||hidden.includes(j))return;for(const x of roots(a,b)){const y=curveValue(a,x);add(x,y,i,'curves');add(x,y,j,'curves');}});
  });
  return result;
}
