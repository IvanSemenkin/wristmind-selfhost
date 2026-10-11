/** Small bounded arithmetic grammar. Model input is data, never executable code. */
type Node = { kind: 'number'; value: number } | { kind: 'x' } | { kind: 'unary'; child: Node; sign: number }
  | { kind: 'binary'; op: string; left: Node; right: Node } | { kind: 'call'; name: string; child: Node };
const functions: Record<string, (x: number) => number> = {
  sin: Math.sin, cos: Math.cos, tan: Math.tan, sqrt: Math.sqrt, abs: Math.abs,
  exp: Math.exp, log: Math.log, ln: Math.log, asin: Math.asin, acos: Math.acos, atan: Math.atan,
};
export type MathFunction = { evaluate: (x: number) => number; barriers: (x: number) => number[]; tex: string };
export function compileExpression(source: string): MathFunction {
  if (source.length > 300) throw new Error('Слишком длинное выражение');
  const normalized = source.replace(/^\s*y\s*=\s*/i, '').replace(/²/g, '^2').replace(/³/g, '^3')
    .replace(/π/g, 'pi').replace(/√\s*(x|pi|e|\d+(?:\.\d+)?)/g, 'sqrt($1)').replace(/√/g, 'sqrt').replace(/[−–]/g, '-').replace(/[×·]/g, '*');
  const tokens = normalized.match(/(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|[a-z]+|[+*/^()-]|\S/g) ?? [];
  if (!tokens.length || tokens.length > 120) throw new Error('Некорректное выражение');
  let position = 0, depth = 0;
  const peek = () => tokens[position];
  const take = () => tokens[position++];
  function atom(): Node {
    if (++depth > 32) throw new Error('Выражение слишком сложное');
    const token = take();
    let node: Node;
    if (token === '(') {
      node = sum();
      if (take() !== ')') throw new Error('Не закрыта скобка');
    } else if (/^(?:\d|\.)/.test(token ?? '') && Number.isFinite(Number(token))) node = {kind:'number', value:Number(token)};
    else if (token === 'x') node = {kind:'x'};
    else if (token === 'pi' || token === 'e') node = {kind:'number',value:token === 'pi' ? Math.PI : Math.E};
    else if (Object.hasOwn(functions, token)) {
      if (take() !== '(') throw new Error('После функции нужны скобки');
      node = {kind:'call',name:token,child:sum()};
      if (take() !== ')') throw new Error('Не закрыта скобка');
    } else throw new Error('Неизвестное имя или символ');
    depth--;
    return node;
  }
  function unary(): Node {
    if (peek() === '+' || peek() === '-') {
      const sign = take() === '-' ? -1 : 1;
      return {kind:'unary',sign,child:unary()};
    }
    const left = atom();
    return peek() === '^' ? (take(), {kind:'binary',op:'^',left,right:unary()}) : left;
  }
  function product(): Node {
    let left = unary();
    while (peek() === '*' || peek() === '/' || /^(?:\d|\.|[a-z]|\()/.test(peek() ?? '')) {
      const op = peek() === '*' || peek() === '/' ? take() : '*';
      left = {kind:'binary',op,left,right:unary()};
    }
    return left;
  }
  function sum(): Node {
    let left = product();
    while (peek() === '+' || peek() === '-') left = {kind:'binary',op:take(),left,right:product()};
    return left;
  }
  const root = sum();
  if (position !== tokens.length) throw new Error('Лишние символы в выражении');
  function value(node: Node, x: number, barriers?: number[]): number {
    switch (node.kind) {
      case 'number': return node.value;
      case 'x': return x;
      case 'unary': return node.sign * value(node.child,x,barriers);
      case 'call': {
        const a = value(node.child,x,barriers);
        if (node.name === 'tan') { const b = Math.cos(a); barriers?.push(b); if (Math.abs(b) < 1e-12) return NaN; }
        return functions[node.name](a);
      }
      case 'binary': {
        const a = value(node.left,x,barriers), b = value(node.right,x,barriers);
        switch (node.op) {
          case '+': return a+b;
          case '-': return a-b;
          case '*': return a*b;
          case '/': barriers?.push(b); return b === 0 ? NaN : a/b;
          default: return a**b;
        }
      }
    }
  }
  function precedence(node: Node): number {
    return node.kind === 'binary' ? node.op === '+' || node.op === '-' ? 1 : node.op === '^' ? 4 : 2 : node.kind === 'unary' ? 3 : 5;
  }
  function tex(node: Node, parent=0): string {
    let result: string;
    switch (node.kind) {
      case 'x': result='x'; break;
      case 'number': result=node.value === Math.PI ? '\\pi' : node.value === Math.E ? 'e' : String(node.value); break;
      case 'unary': result=`${node.sign < 0 ? '-' : '+'}${tex(node.child,3)}`; break;
      case 'call': result=node.name === 'sqrt' ? `\\sqrt{${tex(node.child)}}` : node.name === 'abs' ? `\\left|${tex(node.child)}\\right|` : `\\operatorname{${node.name}}\\left(${tex(node.child)}\\right)`; break;
      case 'binary': {
        if (node.op === '/') result=`\\frac{${tex(node.left)}}{${tex(node.right)}}`;
        else if (node.op === '^') result=`{${tex(node.left,5)}}^{${tex(node.right)}}`;
        else {
          const a=tex(node.left,precedence(node)),b=tex(node.right,precedence(node)+(node.op==='-'?1:0));
          const multiply=node.left.kind==='number' && (node.right.kind==='x' || node.right.kind==='call' || node.right.kind==='binary' && node.right.op==='^') ? '' : '\\cdot ';
          result=`${a}${node.op==='*'?multiply:node.op}${b}`;
        }
        break;
      }
    }
    return precedence(node)<parent ? `\\left(${result}\\right)` : result;
  }
  return { evaluate: x => { const n = value(root,x); return Number.isFinite(n) && Math.abs(n)<=1e12 ? n : NaN; },
    barriers: x => { const result: number[] = []; value(root,x,result); return result; }, tex: `y=${tex(root)}` };
}
