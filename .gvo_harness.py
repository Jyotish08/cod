#!/usr/bin/env python3
"""Local Python method-call GVO harness with transactional SQLite storage."""
import ast, copy, json, sqlite3, sys, traceback
if hasattr(sys, 'set_int_max_str_digits'): sys.set_int_max_str_digits(0)
from pathlib import Path

DB=Path('oj_platform.db')
PROGRESS=Path('.testcase_progress.json')

def _progress(pid,status,cases=0,error=None,unique=None):
    if not PROGRESS.exists(): return
    d=json.loads(PROGRESS.read_text(encoding='utf-8')); item=d['problems'].get(str(pid))
    if item is not None:
        item['status']=status; item['attempts']+=1; item['cases_generated']=cases; item['last_error']=error
        if unique is not None: item['is_unique_output']=unique
    d['meta']['completed']=sum(x['status']=='completed' for x in d['problems'].values())
    d['meta']['failed']=sum(x['status']=='failed' for x in d['problems'].values())
    PROGRESS.write_text(json.dumps(d,indent=2),encoding='utf-8')

class ListNode:
    def __init__(self,val=0,next=None): self.val,self.next=val,next

def _listnode(vals):
    head=tail=None
    for v in vals or []:
        node=ListNode(v)
        if head is None: head=node
        else: tail.next=node
        tail=node
    return head

def _tree(vals):
    if not vals or vals[0] is None: return None
    from collections import deque
    root=TreeNode(vals[0]); q=deque([root]); i=1
    while q and i<len(vals):
        n=q.popleft()
        if i<len(vals) and vals[i] is not None: n.left=TreeNode(vals[i]); q.append(n.left)
        i+=1
        if i<len(vals) and vals[i] is not None: n.right=TreeNode(vals[i]); q.append(n.right)
        i+=1
    return root
class TreeNode:
    def __init__(self,val=0,left=None,right=None): self.val,self.left,self.right,self.next=val,left,right,None
class GraphNode:
    def __init__(self,val=0,neighbors=None): self.val,self.neighbors=val,neighbors or []
class RandomNode:
    def __init__(self,val=0,next=None,random=None): self.val,self.next,self.random=val,next,random

def _random_list(values):
    nodes=[RandomNode(x[0]) for x in values]
    for i,x in enumerate(values):
        nodes[i].next=nodes[i+1] if i+1<len(nodes) else None
        nodes[i].random=nodes[x[1]] if x[1] is not None else None
    return nodes[0] if nodes else None

def _graph(values):
    if not values: return None
    nodes={i+1:GraphNode(i+1) for i in range(len(values))}
    for i,row in enumerate(values): nodes[i+1].neighbors=[nodes[x] for x in row]
    return nodes[1]

def _prep(v,h):
    h=h or ''
    if 'RandomNode' in h and isinstance(v,list): return _random_list(v)
    if 'TreeNode' in h and isinstance(v,list): return _tree(v)
    if 'Node' in h and 'TreeNode' not in h and isinstance(v,list): return _graph(v)
    if 'ListNode' not in h: return v
    if 'Optional[ListNode]' in h or 'list[Optional[ListNode]]' in h or 'List[Optional[ListNode]]' in h:
        return [_listnode(x) for x in v]
    if 'ListNode' in h and isinstance(v,list): return _listnode(v)
    return v

def _ser(v):
    if isinstance(v,ListNode):
        a=[]; seen=set()
        while v is not None and id(v) not in seen: seen.add(id(v)); a.append(v.val); v=v.next
        return a
    if isinstance(v,TreeNode):
        from collections import deque
        a=[]; q=deque([v])
        while q:
            x=q.popleft()
            if x is None: a.append(None)
            else: a.append(x.val); q.extend((x.left,x.right))
        while a and a[-1] is None: a.pop()
        return a
    if isinstance(v,(list,tuple)): return [_ser(x) for x in v]
    if isinstance(v,dict): return {str(k):_ser(x) for k,x in v.items()}
    return v

def _parse_input(s):
    try:
        call=ast.parse('dict('+s+')',mode='eval').body
        if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='dict':
            d={k.arg:ast.literal_eval(k.value) for k in call.keywords if k.arg is not None}
            if d and len(d)==len(call.keywords): return d
    except Exception: pass
    tree=ast.parse(s,mode='exec'); d={}
    for node in tree.body:
        if isinstance(node,ast.Assign):
            val=ast.literal_eval(node.value)
            for t in node.targets:
                if not isinstance(t,ast.Name): raise ValueError('input assignments must use names')
                d[t.id]=val
        elif isinstance(node,ast.AnnAssign) and isinstance(node.target,ast.Name): d[node.target.id]=ast.literal_eval(node.value)
        else: raise ValueError('unsupported sample input syntax')
    return d

def _fmt_input(names,args): return ', '.join(f'{n} = {v!r}' for n,v in zip(names,args))
def _equal(a,b): return a==b

def run(pid, artifact_path):
    a=json.loads(Path(artifact_path).read_text(encoding='utf-8'))
    required={'entry_point','val_code','gen_code','brute_code','opt_code'}
    missing=required-set(a)
    if missing: raise ValueError(f'missing artifact keys: {sorted(missing)}')
    ns={'ListNode':ListNode,'TreeNode':TreeNode,'GraphNode':GraphNode,'RandomNode':RandomNode}
    exec(compile(a['val_code'],'<val_code>','exec'),ns,ns)
    exec(compile(a['gen_code'],'<gen_code>','exec'),ns,ns)
    exec(compile(a['brute_code'],'<brute_code>','exec'),ns,ns)
    exec(compile(a['opt_code'],'<opt_code>','exec'),ns,ns)
    if a.get('serialize_code'): exec(compile(a['serialize_code'],'<serialize_code>','exec'),ns,ns)
    validate,generate=ns['validate'],ns['generate']; entry=a['entry_point']
    def same(x,y):
        if a.get('unordered_output') and isinstance(x,list) and isinstance(y,list):
            return sorted(repr(z) for z in x)==sorted(repr(z) for z in y)
        return _equal(x,y)
    brute,opt=ns['BruteSolution'](),ns['Solution']()
    import inspect
    method=getattr(opt,entry); sig=inspect.signature(method)
    params=list(sig.parameters.values()); names=[p.name for p in params]
    hints={p.name: str(p.annotation) if p.annotation is not inspect.Parameter.empty else '' for p in params}
    def call(obj,args):
        prepared=[_prep(copy.deepcopy(x),hints.get(n,'')) for n,x in zip(names,args)]
        if a.get('tree_node_value_args') and prepared and isinstance(prepared[0],TreeNode):
            by_value={}; stack=[prepared[0]]
            while stack:
                node=stack.pop(); by_value[node.val]=node
                if node.left is not None: stack.append(node.left)
                if node.right is not None: stack.append(node.right)
            for name in a['tree_node_value_args']:
                if name in names: prepared[names.index(name)]=by_value[prepared[names.index(name)]]
        result=getattr(obj,entry)(*prepared)
        return ns['serialize_result'](result) if callable(ns.get('serialize_result')) else _ser(result)
    # Six independent small differential cases.
    for seed in range(1,7):
        args=tuple(generate('small',seed)); validate(*args)
        try: b=call(brute,args); o=call(opt,args)
        except Exception as e: raise RuntimeError(f'differential exception seed={seed}, args={args!r}: {e}') from e
        if not same(b,o): raise AssertionError(f'differential mismatch seed={seed}, args={args!r}, brute={b!r}, opt={o!r}')
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row
    try:
        pid=int(pid)
        p=con.execute('select id from problems where id=?',(pid,)).fetchone()
        if p is None: raise ValueError(f'problem id {pid} does not exist')
        samples=con.execute('select input_data,expected_output from test_cases where problem_id=? and is_sample=1 order by order_index',(pid,)).fetchall()
        skipped_invalid_samples=0
        for i,s in enumerate(samples,1):
            if s['expected_output'].strip() == 'Execution timed out' or s['expected_output'].strip().startswith('Error: '):
                # Legacy importer stored runtime diagnostics as expected output;
                # these rows have no oracle and cannot be compared as samples.
                skipped_invalid_samples += 1
                continue
            values=_parse_input(s['input_data'])
            args=tuple(values[n] for n in names)
            actual=call(opt,args)
            try: expected=ast.literal_eval(s['expected_output'])
            except Exception: expected=s['expected_output']
            if not same(actual,expected):
                raise AssertionError(f'sample mismatch #{i}, input={s["input_data"]!r}, expected={expected!r}, actual={actual!r}')
        suite=[]
        plan=(('small',4),('edge',8),('overflow',4),('stress',4))
        for mode,count in plan:
            for seed in range(1,count+1):
                args=tuple(generate(mode,seed)); validate(*args)
                out=call(opt,args)
                suite.append((_fmt_input(names,args),repr(out),f'GVO verified; mode={mode}, seed={seed}'))
        if len(suite)!=20: raise AssertionError(f'expected 20 cases, generated {len(suite)}')
        # Complete all checks before the transaction; preserve existing cases.
        con.execute('BEGIN IMMEDIATE')
        start=con.execute('select coalesce(max(order_index),0) from test_cases where problem_id=?',(pid,)).fetchone()[0]
        con.executemany('insert into test_cases(problem_id,input_data,expected_output,is_sample,explanation,order_index) values(?,?,?,?,?,?)',
          [(pid,inp,out,0,note,start+i) for i,(inp,out,note) in enumerate(suite,1)])
        con.commit()
        return {'ok':True,'problem_id':pid,'cases_generated':len(suite),'samples_verified':len(samples)-skipped_invalid_samples,'invalid_samples_skipped':skipped_invalid_samples,'is_unique_output':not bool(a.get('unordered_output',False))}
    except Exception:
        con.rollback(); raise
    finally: con.close()

if __name__=='__main__':
    if len(sys.argv)!=3: raise SystemExit('Usage: python .gvo_harness.py <problem_id> <artifacts.json>')
    try:
        result=run(sys.argv[1],sys.argv[2]); _progress(sys.argv[1],'completed',result['cases_generated'],None,result['is_unique_output'])
        print(json.dumps(result,indent=2))
    except Exception as e:
        _progress(sys.argv[1],'failed',0,str(e))
        print(json.dumps({'ok':False,'problem_id':sys.argv[1],'error':str(e)},indent=2)); raise SystemExit(1)

