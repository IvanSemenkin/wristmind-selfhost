import { memo, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { Maximize2, RotateCcw, Plus, Minus, Check } from 'lucide-react';
import { Modal } from '@/components';
import { chartTicks, type AnswerChart as ChartData } from '@/lib/answerChart';
import { chartCurves, chartIntersections, curveValue, initialViewport, panViewport, sampleCurve, zoomViewport, type Curve, type Viewport, type Point } from '@/lib/chartGeometry';
import { renderMathHtml } from '@/lib/richText';
import styles from './AnswerChart.module.css';

const colors=['var(--accent-text)','var(--success-text)','var(--warning-text)','var(--danger-text)','var(--text-primary)','var(--text-secondary)'];
const number=(n:number)=>Math.abs(n)>=10000 || (n!==0 && Math.abs(n)<.001) ? n.toExponential(2).replace('e+','e') : Number(n.toPrecision(5)).toLocaleString('ru-RU');
function Formula({tex, fallback}:{tex?:string;fallback:string}) {
  const html=useMemo(()=>tex ? renderMathHtml(tex,false):null,[tex]);
  return html ? <span dangerouslySetInnerHTML={{__html:html}}/> : <>{fallback}</>;
}
export const AnswerChart = memo(function AnswerChart({chart}:{chart:ChartData}) {
  const curves=useMemo(()=>chartCurves(chart),[chart]);
  const initial=useMemo(()=>initialViewport(chart,curves),[chart,curves]);
  const [view,setView]=useState(initial);
  const [expanded,setExpanded]=useState(false);
  const [hidden,setHidden]=useState<number[]>([]);
  const [resetVersion,setResetVersion]=useState(0);
  const reset=()=>{setView(initial);setResetVersion(n=>n+1);};
  const title=<Formula tex={curves.length===1 ? curves[0].math?.tex : undefined} fallback={chart.title}/>;
  const plot=(large:boolean)=><ChartPlane curves={curves} view={view} onView={setView} hidden={hidden} expanded={large} resetVersion={resetVersion}/>;
  const controls=<>
    <button type="button" aria-label="Уменьшить масштаб графика" title="Уменьшить масштаб" onClick={()=>setView(v=>zoomViewport(v,1.4))}><Minus size={16}/></button>
    <button type="button" aria-label="Увеличить масштаб графика" title="Увеличить масштаб" onClick={()=>setView(v=>zoomViewport(v,1/1.4))}><Plus size={16}/></button>
    <button type="button" aria-label="Сбросить вид графика" title="Исходный вид" onClick={reset}><RotateCcw size={15}/></button>
  </>;
  const legend=(interactive:boolean)=>curves.length>1 && <div className={styles.legend} aria-label="Функции">
    {curves.map((curve,i)=>interactive ? <label key={i} style={{color:colors[i]}}>
      <input type="checkbox" aria-label={`Показать ${curve.label}`} checked={!hidden.includes(i)} onChange={()=>setHidden(prev=>prev.includes(i)?prev.filter(n=>n!==i):[...prev,i])}/>
      <span className={styles.checkMark} aria-hidden="true"><Check size={12}/></span>
      <Formula tex={curve.math?.tex} fallback={curve.label}/>
    </label> : <span key={i} style={{color:colors[i]}}><i/><Formula tex={curve.math?.tex} fallback={curve.label}/></span>)}
  </div>;
  return <>
    <figure className={styles.card}>
      <div className={styles.header}><figcaption className={styles.title}>{title}</figcaption>
        <div className={styles.controls}>{controls}<button type="button" title="Раскрыть график" aria-label="Раскрыть график" onClick={()=>setExpanded(true)}><Maximize2 size={16}/></button></div>
      </div>
      {!expanded && plot(false)}
      {expanded && <div className={styles.placeholder}>График открыт в расширенном режиме</div>}
      {legend(false)}
    </figure>
    <Modal open={expanded} onClose={()=>setExpanded(false)} title={chart.title} size="xl">
      <div className={styles.expanded}>
        <div className={styles.expandedHeader}>{curves.length===1&&<div className={styles.title}>{title}</div>}<div className={styles.controls}>{controls}</div></div>
        {expanded && plot(true)}{legend(true)}
      </div>
    </Modal>
  </>;
});

type Selection={x:number;y:number;curve:number;kind?:'x-axis'|'y-axis'|'curves'};
function ChartPlane({curves,view,onView,hidden,expanded,resetVersion}:{curves:Curve[];view:Viewport;onView:(v:Viewport)=>void;hidden:number[];expanded:boolean;resetVersion:number}) {
  const svg=useRef<SVGSVGElement>(null),id=useId();
  const [size,setSize]=useState({width:550,height:280});
  const [active,setActive]=useState(expanded);
  useEffect(()=>{
    const element=svg.current;if(!element||expanded)return;
    const observer=new IntersectionObserver(([entry])=>setActive(entry.isIntersecting),{rootMargin:"160px"});
    observer.observe(element);return()=>observer.disconnect();
  },[expanded]);
  const [hover,setHover]=useState<Selection|null>(null),[pinned,setPinned]=useState<Selection|null>(null);
  const current=useRef(view);current.current=view;
  const frame=useRef<number>(0),pending=useRef<Viewport|null>(null);
  const requestView=(v:Viewport)=>{pending.current=v;current.current=v;if(!frame.current)frame.current=requestAnimationFrame(()=>{frame.current=0;if(pending.current)onView(pending.current);});};
  useEffect(()=>()=>cancelAnimationFrame(frame.current),[]);
  useEffect(()=>{setPinned(null);setHover(null);pending.current=null;cancelAnimationFrame(frame.current);frame.current=0;},[resetVersion]);
  useEffect(()=>{
    if(!svg.current)return;
    const observer=new ResizeObserver(([e])=>setSize({width:Math.max(180,e.contentRect.width),height:e.contentRect.height}));
    observer.observe(svg.current);return()=>observer.disconnect();
  },[]);
  const {width,height}=size;
  const left=48,top=16,right=width-48,bottom=height-34,pw=right-left,ph=bottom-top;
  const x=(v:number)=>left+(v-view.minX)/(view.maxX-view.minX)*pw;
  const y=(v:number)=>bottom-(v-view.minY)/(view.maxY-view.minY)*ph;
  const retainedPaths=useRef<Point[][][]>([]);
  const paths=useMemo(()=>{
    // Keep the last geometry when a card leaves the viewport: returning to it
    // or resizing an overlay must not flash an empty coordinate plane.
    if(!active)return retainedPaths.current;
    const result=curves.map((c,i)=>hidden.includes(i)?[]:sampleCurve(c,view,pw));
    retainedPaths.current=result;
    return result;
  },[curves,view,pw,hidden,active]);
  const intersections=useMemo(()=>active?chartIntersections(curves,view,hidden):[],[active,curves,view,hidden]);
  const xTicks=chartTicks(view.minX,view.maxX,Math.max(2,Math.floor(pw/85)));
  const yTicks=chartTicks(view.minY,view.maxY,Math.max(2,Math.floor(ph/48)));
  const axisX=Math.max(top,Math.min(bottom,y(0))),axisY=Math.max(left,Math.min(right,x(0)));
  const normalized=(clientX:number,clientY:number)=>{
    const rect=svg.current!.getBoundingClientRect();
    return {x:(clientX-rect.left-left)/pw,y:(clientY-rect.top-top)/ph};
  };
  useEffect(()=>{
    const element=svg.current;if(!element)return;
    const wheel=(e:WheelEvent)=>{
      const p=normalized(e.clientX,e.clientY);
      if(p.x<0||p.x>1||p.y<0||p.y>1)return;
      e.preventDefault();
      requestView(zoomViewport(current.current,Math.exp(Math.max(-.3,Math.min(.3,e.deltaY*(e.deltaMode===1?.04:.002)))),p.x,p.y));
    };
    element.addEventListener('wheel',wheel,{passive:false});
    return()=>element.removeEventListener('wheel',wheel);
  },[pw,ph,left,top]);
  const nearest=(clientX:number,clientY:number):Selection|null=>{
    const p=normalized(clientX,clientY);
    if(p.x<0||p.x>1||p.y<0||p.y>1)return null;
    const xx=view.minX+p.x*(view.maxX-view.minX),yy=view.maxY-p.y*(view.maxY-view.minY);
    const choices=curves.flatMap((c,i)=>{const value=curveValue(c,xx);return hidden.includes(i)||!Number.isFinite(value)||value<view.minY||value>view.maxY?[]:[{x:xx,y:value,curve:i}];});
    const closest=choices.sort((a,b)=>Math.abs(a.y-yy)-Math.abs(b.y-yy))[0];
    if(!closest)return null;
    const snapped=intersections.filter(point=>point.curve===closest.curve)
      .map(point=>({point,distance:Math.hypot(x(point.x)-x(closest.x),y(point.y)-y(closest.y))}))
      .filter(candidate=>candidate.distance<=12).sort((a,b)=>a.distance-b.distance)[0];
    return snapped?.point??closest;
  };
  const pointers=useRef(new Map<number,{x:number;y:number}>());
  const moved=useRef(false),origin=useRef({x:0,y:0});
  const holdTimer=useRef<number|null>(null),probePointer=useRef<number|null>(null);
  const [probing,setProbing]=useState(false);
  const cancelHold=()=>{if(holdTimer.current!==null)window.clearTimeout(holdTimer.current);holdTimer.current=null;};
  const clearProbe=()=>{cancelHold();probePointer.current=null;setProbing(false);};
  useEffect(()=>()=>{if(holdTimer.current!==null)window.clearTimeout(holdTimer.current);},[]);
  const down=(e:ReactPointerEvent<SVGSVGElement>)=>{
    if(e.button!==0)return;
    const p=normalized(e.clientX,e.clientY);if(p.x<0||p.x>1||p.y<0||p.y>1)return;
    e.currentTarget.setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId,{x:e.clientX,y:e.clientY});
    if(pointers.current.size===1){moved.current=false;origin.current={x:e.clientX,y:e.clientY};}
    else {moved.current=true;clearProbe();}
    if(e.pointerType==='touch'&&pointers.current.size===1) {
      const pointerId=e.pointerId;
      cancelHold();
      holdTimer.current=window.setTimeout(()=>{
        holdTimer.current=null;
        const pointer=pointers.current.get(pointerId);
        if(!pointer||pointers.current.size!==1||moved.current)return;
        probePointer.current=pointerId;setProbing(true);setPinned(null);
        setHover(nearest(pointer.x,pointer.y));
      },450);
    }
  };
  const move=(e:ReactPointerEvent<SVGSVGElement>)=>{
    const previous=pointers.current.get(e.pointerId);
    if(!previous){if(!pinned)setHover(nearest(e.clientX,e.clientY));return;}
    const before=[...pointers.current.values()];
    pointers.current.set(e.pointerId,{x:e.clientX,y:e.clientY});
    const after=[...pointers.current.values()];
    if(probePointer.current===e.pointerId){setHover(nearest(e.clientX,e.clientY));return;}
    if(Math.hypot(e.clientX-origin.current.x,e.clientY-origin.current.y)>4)moved.current=true;
    if(!moved.current)return;
    cancelHold();
    setHover(null);
    if(before.length>=2){
      const distance=(p:{x:number;y:number}[])=>Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y);
      const center=(p:{x:number;y:number}[])=>({x:(p[0].x+p[1].x)/2,y:(p[0].y+p[1].y)/2});
      const a=center(before),b=center(after),n=normalized(a.x,a.y),d=distance(after);
      if(d>8)requestView(panViewport(zoomViewport(current.current,distance(before)/d,n.x,n.y),(b.x-a.x)/pw,(b.y-a.y)/ph));
    } else requestView(panViewport(current.current,(e.clientX-previous.x)/pw,(e.clientY-previous.y)/ph));
  };
  const up=(e:ReactPointerEvent<SVGSVGElement>)=>{
    if(!pointers.current.has(e.pointerId))return;
    const selection=nearest(e.clientX,e.clientY);
    if(probePointer.current===e.pointerId){setPinned(selection?.kind?selection:null);setHover(null);clearProbe();}
    else {cancelHold();if(!moved.current)setPinned(selection?.kind?selection:null);}
    pointers.current.delete(e.pointerId);
    if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);
  };
  const point=pinned??hover;
  const visiblePoint=point&&!hidden.includes(point.curve)&&point.x>=view.minX&&point.x<=view.maxX&&point.y>=view.minY&&point.y<=view.maxY?point:null;
  const noData=active&&paths.every(segments=>!segments.some(s=>s.some((p,i)=>i>0&&p[0]>=view.minX&&s[i-1][0]<=view.maxX&&Math.max(p[1],s[i-1][1])>=view.minY&&Math.min(p[1],s[i-1][1])<=view.maxY)));
  return <div className={`${styles.plane} ${expanded?styles.large:''}`}>
    <svg ref={svg} viewBox={`0 0 ${width} ${height}`} className={styles.canvas} data-probing={probing||undefined} role="img" aria-label="Интерактивный график. Стрелки перемещают область, плюс и минус меняют масштаб, Escape снимает выбор точки." tabIndex={0}
      onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={e=>{pointers.current.delete(e.pointerId);moved.current=true;clearProbe();setHover(null);}} onLostPointerCapture={e=>{pointers.current.delete(e.pointerId);if(probePointer.current===e.pointerId)clearProbe();}} onContextMenu={e=>e.preventDefault()} onPointerLeave={()=>setHover(null)}
      onKeyDown={e=>{if(e.key==='Escape'){setPinned(null);setHover(null);return;}const offsets:Record<string,[number,number]>={ArrowLeft:[.1,0],ArrowRight:[-.1,0],ArrowUp:[0,.1],ArrowDown:[0,-.1]};if(offsets[e.key]){e.preventDefault();requestView(panViewport(current.current,...offsets[e.key]));}else if(['+','=','-'].includes(e.key)){e.preventDefault();requestView(zoomViewport(current.current,e.key==='-'?1.4:1/1.4));}}}>
      <defs><clipPath id={id}><rect x={left} y={top} width={pw} height={ph}/></clipPath></defs>
      <g className={styles.grid}>{xTicks.map(t=><line key={`x${t}`} x1={x(t)} x2={x(t)} y1={top} y2={bottom}/>)}{yTicks.map(t=><line key={`y${t}`} x1={left} x2={right} y1={y(t)} y2={y(t)}/>)}</g>
      <g className={styles.axes}><line x1={left} x2={right} y1={axisX} y2={axisX}/><line x1={axisY} x2={axisY} y1={top} y2={bottom}/>
        {xTicks.map(t=><line key={`x${t}`} x1={x(t)} x2={x(t)} y1={axisX-3} y2={axisX+3}/>)}{yTicks.map(t=><line key={`y${t}`} x1={axisY-3} x2={axisY+3} y1={y(t)} y2={y(t)}/>)}</g>
      <g className={styles.labels}>{xTicks.map(t=><text key={`x${t}`} x={x(t)} y={bottom+20} textAnchor="middle">{number(t)}</text>)}{yTicks.map(t=><text key={`y${t}`} x={left-8} y={y(t)} dominantBaseline="middle" textAnchor="end">{number(t)}</text>)}<text x={right} y={Math.max(top+12,Math.min(bottom-8,axisX-8))} textAnchor="end">x</text><text x={Math.min(right-12,axisY+9)} y={top+10}>y</text></g>
      <g clipPath={`url(#${id})`}>{paths.map((segments,i)=><path key={i} data-curve={i} d={segments.map(s=>s.map((p,j)=>`${j?'L':'M'}${Math.max(-1e6,Math.min(1e6,x(p[0])))},${Math.max(-1e6,Math.min(1e6,y(p[1])))}`).join(' ')).join(' ')} fill="none" stroke={colors[i]} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round"/>)}
        {visiblePoint&&<g><line className={styles.crosshair} x1={x(point!.x)} x2={x(point!.x)} y1={top} y2={bottom}/><circle cx={x(point!.x)} cy={y(point!.y)} r={probing?6:point!.kind?5:4} fill={colors[point!.curve]} stroke="var(--bg-surface)" strokeWidth="2"/></g>}
      </g>
    </svg>
    {visiblePoint&&<output className={styles.coordinates} style={{left:Math.max(48,Math.min(width-180,x(visiblePoint.x)+10)),top:Math.max(8,Math.min(height-52,y(visiblePoint.y)-40))}}>{visiblePoint.kind&&<span className={styles.snapLabel}>{visiblePoint.kind==='curves'?'Пересечение функций':visiblePoint.kind==='x-axis'?'Пересечение с X':'Пересечение с Y'}</span>}<span>x: {number(visiblePoint.x)} · y: {number(visiblePoint.y)}</span> {pinned&&<button type="button" aria-label="Снять выбор точки" onClick={()=>{setPinned(null);setHover(null);}}>×</button>}</output>}
    {noData&&<div className={styles.empty}>{hidden.length===curves.length?'Все функции скрыты':'В этой области нет точек графика'}</div>}
  </div>;
}
