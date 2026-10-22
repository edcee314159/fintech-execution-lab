"""Durable synthetic order intents and conservative reconciliation; no broker adapter."""
from pathlib import Path
from contextlib import contextmanager
import copy,hashlib,json,math,os,random,re

SCENARIOS=('mixed','lost_ack','cancel_race','unresolved')
LIMITS=('全部为本地模拟券商与人工故障，未接任何真实账户。先保存意图再发送，未知订单不因超时或列表中缺失而重发。'
        '完整订单、成交和持仓快照一致后才能释放预留量。模拟快照包含此母单全部历史，真实接口不一定提供同样原子性、完整性或幂等契约。'
        '日志指纹用于发现意外变更，不是防攻击签名；仅支持单写者，破损或锁遗留时停止，不自动修复。'
        '不支持交易撤销、更正、外部手工订单、多账户或成交冲正；矛盾回报暂停等待核实。不能据此宣称跨券商恰好执行一次。')

def options(p):
    if not isinstance(p,dict) or set(p)!={'quantity','scenario','seed'}:raise ValueError('请提供数量、人工故障情形和随机种子。')
    for k,lo,hi in [('quantity',1,100000),('seed',0,2**32-1)]:
        if isinstance(p[k],bool) or not isinstance(p[k],int) or not lo<=p[k]<=hi:raise ValueError(k+' 超出支持范围。')
    if p['scenario'] not in SCENARIOS:raise ValueError('未知人工故障。')
    return dict(p)

def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def integer(v,lo=0,hi=100000):
    if isinstance(v,bool) or not isinstance(v,int) or not lo<=v<=hi:raise ValueError('无效整数数量或序号。')
    return v
def snapshot(seq,orders,executions,position,complete=True):
    return {'seq':seq,'orders':copy.deepcopy(orders),'executions':copy.deepcopy(executions),'position':position,'complete':complete}

class OrderLedger:
    """Append-only, fsync-before-apply journal; each reopen requires reconciliation."""
    def __init__(self,path,quantity):
        integer(quantity,1);self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=self.path.with_suffix('.lock');self.rows=[];self.raw=b''
        self.state={'quantity':quantity,'orders':{},'executions':{},'connected':True,'ready':False,
                    'snapshot_seq':-1,'duplicates':0,'fault':None}
        with self._locked():
            if self.path.exists():
                self.raw=self.path.read_bytes()
                if not self.raw or not self.raw.endswith(b'\n'):raise ValueError('日志尾部不完整，停止恢复。')
                previous='0'*64
                try:
                    for i,line in enumerate(self.raw.splitlines(),1):
                        row=json.loads(line)
                        if set(row)!={'seq','previous','event','sha256'}:raise ValueError()
                        body={k:row[k] for k in ('seq','previous','event')}
                        if row['seq']!=i or row['previous']!=previous or hashlib.sha256(canonical(body)).hexdigest()!=row['sha256']:raise ValueError()
                        self._apply(self.state,row['event']);self.rows.append(row);previous=row['sha256']
                except (ValueError,KeyError,TypeError,UnicodeError) as e:
                    raise ValueError('日志内容或指纹不一致，停止恢复。') from e
                self._append_unlocked({'kind':'restart'})
            else:
                self._append_unlocked({'kind':'init','quantity':quantity})

    @contextmanager
    def _locked(self):
        try:fd=os.open(self.lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:raise ValueError('日志存在写锁；需核实其他写者或中断，不自动解除。') from None
        try:yield
        finally:os.close(fd);self.lock.unlink()

    @staticmethod
    def _apply(s,e):
        k=e['kind'];orders=s['orders']
        if k=='init':
            if e['quantity']!=s['quantity']:raise ValueError('母单数量不一致。')
        elif k in ('disconnect','restart','cancel','fault'):
            s['ready']=False
            if k in ('disconnect','restart'):s['connected']=False
            if k=='cancel':
                if e['client_id'] not in orders:raise ValueError('找不到撤单意图。')
                orders[e['client_id']]['cancel_pending']=True
            if k=='fault':s['fault']=e['reason']
        elif k=='reconnect':s['connected']=True;s['ready']=False
        elif k=='intent':
            q=integer(e['quantity'],1);oid=e['client_id']
            reserved=sum(o['quantity']-o['filled'] for o in orders.values() if not o['terminal'])
            known=sum(o['filled'] for o in orders.values())
            if not s['connected'] or not s['ready'] or q>s['quantity']-known-reserved or oid in orders:raise ValueError('状态未核实或可安全分配的数量不足。')
            orders[oid]={'quantity':q,'filled':0,'terminal':False,'confirmed':False,'cancel_pending':False}
            s['ready']=False
        elif k=='execution':
            x=e['execution'];oid=x['client_id'];eid=x['execution_id'];q=integer(x['quantity'],1)
            if set(x)!={'client_id','execution_id','quantity'} or not isinstance(eid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',eid) or oid not in orders:raise ValueError('无效成交回报。')
            if eid in s['executions']:
                if s['executions'][eid]!=x:raise ValueError('相同成交ID内容冲突。')
                s['duplicates']+=1;return
            total=sum(v['quantity'] for v in s['executions'].values() if v['client_id']==oid)+q
            o=orders[oid]
            if total>o['quantity'] or (o['terminal'] and total>o['filled']):raise ValueError('成交量超过已确认订单终态。')
            s['executions'][eid]=copy.deepcopy(x);o['filled']=max(o['filled'],total)
        elif k=='status':
            oid=e['client_id'];q=integer(e['filled'])
            if oid not in orders or e['status'] not in ('active','cancelled','filled','rejected') or q>orders[oid]['quantity']:raise ValueError('无效订单回报。')
            o=orders[oid]
            if o['terminal'] and q>o['filled']:raise ValueError('订单终态与新累计成交矛盾。')
            o['filled']=max(o['filled'],q)
            if e['status']!='active' and not o['terminal']:s['ready']=False
        elif k=='reconcile':
            v=e['snapshot']
            if set(v)!={'seq','orders','executions','position','complete'} or v['complete'] is not True:raise ValueError('快照不完整。')
            if not s['connected'] or integer(v['seq'],0,10**12)<=s['snapshot_seq']:raise ValueError('连接未恢复或快照已过期。')
            if not isinstance(v['orders'],list) or not isinstance(v['executions'],list):raise ValueError('无效快照。')
            got={}
            for o in v['orders']:
                if set(o)!={'client_id','quantity','filled','status'} or o['client_id'] in got:raise ValueError('订单快照重复或字段不正确。')
                oid=o['client_id']
                if oid not in orders or integer(o['quantity'],1)!=orders[oid]['quantity']:raise ValueError('快照缺少本地意图或存在外部订单。')
                q=integer(o['filled']);status=o['status']
                if q>o['quantity'] or q<orders[oid]['filled'] or status not in ('active','cancelled','filled','rejected'):raise ValueError('订单累计数量或状态不一致。')
                if (status=='filled' and q!=o['quantity']) or (status=='rejected' and q!=0) or (orders[oid]['terminal'] and (status=='active' or q!=orders[oid]['filled'])):raise ValueError('订单终态不一致。')
                got[oid]=o
            if set(got)!=set(orders):raise ValueError('未找到未知订单不代表未被接收。')
            executions={}
            for x in v['executions']:
                if set(x)!={'execution_id','client_id','quantity'} or x['client_id'] not in got or x['execution_id'] in executions:raise ValueError('成交快照重复或不匹配。')
                integer(x['quantity'],1);executions[x['execution_id']]=x
            if any(executions.get(eid)!=x for eid,x in s['executions'].items()):raise ValueError('已知成交在快照中缺失或被改写。')
            for oid,o in got.items():
                if sum(x['quantity'] for x in executions.values() if x['client_id']==oid)!=o['filled']:raise ValueError('累计状态与完整成交明细不一致。')
            if integer(v['position'])!=s['quantity']-sum(o['filled'] for o in got.values()):raise ValueError('持仓与成交不一致。')
            committed=sum(o['quantity'] if o['status']=='active' else o['filled'] for o in got.values())
            if committed>s['quantity']:raise ValueError('已确认成交与仍可能成交量超过母单。')
            for oid,o in got.items():
                orders[oid].update(filled=o['filled'],terminal=o['status']!='active',confirmed=True,cancel_pending=False)
            s.update(executions=copy.deepcopy(executions),snapshot_seq=v['seq'],ready=True,fault=None)
        else:raise ValueError('未知日志事件。')

    def _append_unlocked(self,event):
        current=self.path.read_bytes() if self.path.exists() else b''
        if current!=self.raw:raise ValueError('日志已被其他写者改变，停止提交。')
        state=copy.deepcopy(self.state);self._apply(state,event)
        body={'seq':len(self.rows)+1,'previous':self.rows[-1]['sha256'] if self.rows else '0'*64,'event':copy.deepcopy(event)}
        row={**body,'sha256':hashlib.sha256(canonical(body)).hexdigest()};line=canonical(row)+b'\n'
        with self.path.open('ab') as f:f.write(line);f.flush();os.fsync(f.fileno())
        self.raw+=line;self.rows.append(row);self.state=state
    def append(self,event):
        with self._locked():self._append_unlocked(event)
    def intent(self,quantity):
        oid='I'+str(len(self.state['orders'])+1).zfill(6)
        self.append({'kind':'intent','client_id':oid,'quantity':quantity});return oid
    def execution(self,x):
        try:self.append({'kind':'execution','execution':x});return True
        except (ValueError,KeyError,TypeError) as e:
            self.append({'kind':'fault','reason':str(e)});return False
    def status(self,oid,filled,status):
        try:self.append({'kind':'status','client_id':oid,'filled':filled,'status':status});return True
        except (ValueError,KeyError,TypeError) as e:
            self.append({'kind':'fault','reason':str(e)});return False
    def cancel(self,oid):self.append({'kind':'cancel','client_id':oid})
    def disconnect(self):self.append({'kind':'disconnect'})
    def reconnect(self):self.append({'kind':'reconnect'})
    def reconcile(self,value):
        try:self.append({'kind':'reconcile','snapshot':value});return True
        except (ValueError,KeyError,TypeError) as e:
            self.append({'kind':'fault','reason':str(e)});return False
    def summary(self):
        s=self.state;known=sum(o['filled'] for o in s['orders'].values())
        reserved=sum(o['quantity']-o['filled'] for o in s['orders'].values() if not o['terminal'])
        ready=s['ready'] and s['connected'] and not s['fault']
        return {'confirmed_filled':known,'reserved':reserved,'available':max(0,s['quantity']-known-reserved) if ready else 0,
                'ready':bool(ready),'connected':s['connected'],'duplicates':s['duplicates'],
                'unknown_orders':sum(not o['confirmed'] or o['cancel_pending'] for o in s['orders'].values()),
                'fault':s['fault'],'journal_seq':len(self.rows)}

class MockBroker:
    """Finite synthetic contract: complete atomic parent-scoped snapshots, stable client IDs."""
    def __init__(self,quantity):self.quantity=quantity;self.orders={};self.executions=[];self.seq=0;self.repeats=0
    def submit(self,oid,q):
        if oid in self.orders:
            if self.orders[oid]['quantity']!=q:raise ValueError('幂等键内容冲突。')
            self.repeats+=1;return
        self.orders[oid]={'client_id':oid,'quantity':q,'filled':0,'status':'active'}
    def fill(self,oid,q):
        o=self.orders[oid];q=min(q,o['quantity']-o['filled']) if o['status']=='active' else 0
        if not q:return None
        x={'execution_id':'E'+str(len(self.executions)+1),'client_id':oid,'quantity':q}
        o['filled']+=q
        if o['filled']==o['quantity']:o['status']='filled'
        self.executions.append(x);return x
    def cancel(self,oid):
        if self.orders[oid]['status']=='active':self.orders[oid]['status']='cancelled'
    def snap(self,complete=True,omit=False):
        self.seq+=1;filled=sum(x['quantity'] for x in self.executions)
        return snapshot(self.seq,[] if omit else list(self.orders.values()),[] if omit else self.executions,
                        self.quantity-filled,complete)
    @property
    def filled(self):return sum(x['quantity'] for x in self.executions)

def run_study(payload,folder):
    c=options(payload);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    q=c['quantity'];scenario=c['scenario'];rng=random.Random(c['seed']);child=max(1,math.ceil(.6*q))
    first_quantity=max(1,round(child*rng.uniform(.25,.35)))
    l=OrderLedger(folder/'orders.jsonl',q);broker=MockBroker(q);trace=[]
    def record(action):
        s=l.summary();trace.append({'step':len(trace),'action':action,'known_filled':s['confirmed_filled'],
            'reserved':s['reserved'],'available':s['available'],'ready':s['ready'],'connected':s['connected'],
            'unknown_orders':s['unknown_orders'],'actual_filled':broker.filled,'actual_position':q-broker.filled,'fault':s['fault']})
    l.reconcile(broker.snap());record('核对初始持仓与空订单')
    oid=l.intent(child);record('先持久化下单意图，再发送')
    broker.submit(oid,child)
    if scenario=='cancel_race':l.reconcile(broker.snap())
    first=broker.fill(oid,first_quantity)
    if first:l.execution(first);l.execution(first);l.status(oid,first['quantity'],'active')
    record('重复成交回报按唯一ID去重')
    l.disconnect();record('断线：禁止新单，保留可能成交量')
    broker.fill(oid,first_quantity)
    if scenario=='mixed':l=OrderLedger(folder/'orders.jsonl',q);record('重启：从落盘事件重建，仍需对账')
    l.reconnect()
    l.reconcile(broker.snap(complete=False));record('拒绝不完整快照，保持预留')
    try:l.intent(1)
    except ValueError:record('状态未核实，拦截重发')
    if scenario=='unresolved':
        l.reconcile(broker.snap(omit=True));record('列表缺失不等于未接收，停止等待核实')
    else:
        l.reconcile(broker.snap());record('订单、完整成交与持仓一致后恢复')
        if scenario in ('mixed','cancel_race'):
            l.cancel(oid);record('请求撤单：尚未生效，不释放剩余')
            broker.fill(oid,max(1,child//6));record('撤单生效前仍可能成交')
            broker.cancel(oid);l.status(oid,broker.orders[oid]['filled'],'cancelled')
            record('收到撤单状态，仍等待完整对账')
            l.reconcile(broker.snap());record('确认终态后释放未成交预留')
        else:
            broker.fill(oid,child);l.reconcile(broker.snap());record('找回断线期间的成交')
        left=l.summary()['available']
        if left:
            new=l.intent(left);broker.submit(new,left);broker.fill(new,left)
            l.reconcile(broker.snap());record('仅发送核对后的安全剩余数量')
    safe={'planner':'reconciled','actual_filled':broker.filled,'residual':max(0,q-broker.filled),
          'oversold':max(0,broker.filled-q),'duplicate_order_submissions':broker.repeats,
          'known_filled':l.summary()['confirmed_filled'],'trace':trace,'complete':broker.filled==q}
    # Deliberately unsafe timeout-resend example, using fresh order IDs for the same intent.
    naive=MockBroker(q);naive.submit('old',child);naive.fill('old',first_quantity)
    naive_trace=[{'step':0,'action':'发送后未收到确认','known_filled':0,'reserved':0,'available':q,'ready':True,'actual_filled':naive.filled,'actual_position':q-naive.filled,'unknown_orders':1,'connected':True,'fault':None}]
    naive.submit('retry',child)
    naive.fill('old',child);naive.fill('retry',child)
    if naive.filled<q:naive.submit('finish',q-naive.filled);naive.fill('finish',q-naive.filled)
    naive_trace.append({'step':1,'action':'超时换新ID重发，原单也继续成交','known_filled':naive.filled,'reserved':0,'available':0,'ready':True,'actual_filled':naive.filled,'actual_position':q-naive.filled,'unknown_orders':0,'connected':True,'fault':None})
    unsafe={'planner':'timeout_retry','actual_filled':naive.filled,'residual':max(0,q-naive.filled),
            'oversold':max(0,naive.filled-q),'duplicate_order_submissions':1,'known_filled':naive.filled,
            'trace':naive_trace,'complete':naive.filled==q}
    policies={'timeout_retry':unsafe,'reconciled':safe}
    summary={'quantity':q,'scenario':scenario,'strategies':[{k:v for k,v in row.items() if k!='trace'} for row in policies.values()]}
    return {'recovery_schema':'recovery-1.0','data_kind':'synthetic_broker_faults','design':c,
            'policies':policies,'journal':l.rows,'dashboard_summary':summary,'limitations':LIMITS,
            'baseline_note':'超时重发是故意缺少保护的故障示例；两条轨迹的步骤不同，不用于收益或速度排名。'}
