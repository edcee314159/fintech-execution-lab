"""Bounded background studies using local uploads and the existing research kernel."""
from pathlib import Path
from datetime import datetime,timezone
import csv,io,json,hashlib,re,threading,uuid,importlib.util
import numpy as np
from execution_volume_validation.data import load_sessions
from execution_volume_validation.study import run_study

_spec=importlib.util.spec_from_file_location('execution_dashboard_reports',Path(__file__).with_name('research_reports.py'))
_reports=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_reports)
safe_text=_reports.safe_text
_adaptive_spec=importlib.util.spec_from_file_location('execution_dashboard_adaptive',Path(__file__).with_name('adaptive_execution.py'))
_adaptive=importlib.util.module_from_spec(_adaptive_spec);_adaptive_spec.loader.exec_module(_adaptive)

def _tool(name):
    spec=importlib.util.spec_from_file_location('execution_'+name,Path(__file__).with_name(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

_signal=_tool('signal_execution')
_orderbook=_tool('orderbook_execution')



def identifier(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):
        raise ValueError('记录编号不正确。')
    return value


def write_json(path,data):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    temporary.replace(path)


def options(payload):
    required={'upload_id','lookback','evaluation_days','fraction','participation_rate'}
    if not isinstance(payload,dict) or set(payload)!=required:
        raise ValueError('请提供上传编号、回看天数、评估天数、订单占比和参与上限。')
    identifier(payload['upload_id'])
    for key,low,high in [('lookback',2,20),('evaluation_days',1,60)]:
        if isinstance(payload[key],bool) or not isinstance(payload[key],int) or not low<=payload[key]<=high:
            raise ValueError(f'{key} 必须是 {low} 至 {high} 的整数。')
    if isinstance(payload['fraction'],bool) or payload['fraction'] not in (.01,.05,.09):
        raise ValueError('订单占比仅支持 1%、5%、9%。')
    rate=payload['participation_rate']
    if isinstance(rate,bool) or not isinstance(rate,(float,int)) or not .01<=rate<=.25:
        raise ValueError('成交参与上限须在 1% 至 25% 之间。')
    return dict(payload)


def summarize_rows(records):
    rows=[]
    for predictor in ('uniform','historical_shape','previous_day'):
        for planner in ('twap_capped','volume_capped','arrival_constrained'):
            data=[r for r in records if r['predictor']==predictor and r['planner']==planner]
            if not data:continue
            planned=[r for r in data if r['planning_feasible']]
            rows.append({'predictor':predictor,'planner':planner,'cases':len(data),'dates':len({r['date'] for r in data}),
                         'planned':len(planned),'completed':sum(bool(r['replay'] and r['replay']['complete']) for r in data),
                         'mean_residual_planned':float(np.mean([r['replay']['residual'] for r in planned])) if planned else None})
    return rows


def regime(value,history):
    baseline=float(np.median(history))
    if baseline==0:return '常态' if value==0 else '高'
    return '低' if value<.8*baseline else ('高' if value>1.2*baseline else '常态')


class WorkflowService:
    def __init__(self,output,uploads_from=None,*,validator,normalizer):
        self.output=Path(output).resolve();self.output.mkdir(parents=True,exist_ok=True)
        self.inputs=[self.output]
        if uploads_from is not None and Path(uploads_from).resolve()!=self.output:
            self.inputs.append(Path(uploads_from).resolve())
        self.validator=validator;self.normalizer=normalizer
        self.work_lock=threading.Lock();self.state_lock=threading.Lock();self.states={}

    @property
    def running(self):return self.work_lock.locked()

    def upload_folder(self,upload_id):
        identifier(upload_id)
        for root in self.inputs:
            base=(root/'uploads').resolve();folder=(base/upload_id).resolve()
            if folder.parent==base and (folder/'audit.json').is_file():return folder
        raise ValueError('找不到该上传记录，请刷新列表或重新上传。')

    def list_uploads(self):
        records={}
        for root in self.inputs:
            for path in (root/'uploads').glob('*/audit.json'):
                try:
                    key=identifier(path.parent.name);a=json.loads(path.read_text(encoding='utf-8'))
                    if key in records:continue
                    records[key]={'id':key,'symbol':a['symbol'],'complete_sessions':a['complete_sessions'],
                                  'format_valid':a['format_valid'],'ready_for_pilot':a['ready_for_pilot'],
                                  'origin_note':a.get('origin_note','用户本地输入，真实性未独立核实'),
                                  'dates':a['usable_dates']}
                except (ValueError,KeyError,OSError):continue
        return sorted(records.values(),key=lambda r:(r['dates'][-1] if r['dates'] else '',r['id']),reverse=True)

    def _set(self,key,**changes):
        with self.state_lock:
            self.states[key].update(changes)
            write_json(self.output/'rolling'/key/'state.json',self.states[key])

    def status(self,key):
        identifier(key)
        with self.state_lock:
            if key in self.states:return json.loads(json.dumps(self.states[key]))
        path=self.output/'rolling'/key/'state.json'
        if not path.is_file():raise ValueError('任务不存在。')
        state=json.loads(path.read_text(encoding='utf-8'))
        if state['status'] in ('queued','running'):
            state.update(status='failed',phase='服务曾重启；该任务未确认完成，请重新运行。')
        return state

    def start(self,payload,*,adaptive=False):
        return self._start(options(payload),'adaptive' if adaptive else 'rolling')

    def start_signal(self,payload):
        if not isinstance(payload,dict) or set(payload)!={'upload_id','lookback','evaluation_days','fraction','participation_rate','signal_scenario'}:
            raise ValueError('请提供行情参数和信号情形。')
        scenario=payload['signal_scenario']
        if scenario not in _signal.SCENARIOS:raise ValueError('信号情形须为历史模型、无信号或反向信号。')
        config=options({k:v for k,v in payload.items() if k!='signal_scenario'});config['signal_scenario']=scenario
        return self._start(config,'signal')

    def start_orderbook(self,payload):
        return self._start(_orderbook.options(payload),'orderbook')

    def _start(self,config,kind):
        if not self.work_lock.acquire(blocking=False):raise ValueError('已有滚动任务运行中，请等待其完成。')
        key=uuid.uuid4().hex
        try:
            (self.output/'rolling'/key).mkdir(parents=True)
            self.states[key]={'id':key,'status':'queued','phase':'等待核对输入','parameters':config,'kind':kind}
            self._set(key)
            threading.Thread(target=self._worker,args=(key,config,kind),daemon=True).start()
        except Exception:
            self.work_lock.release();raise
        return self.status(key)

    def _worker(self,key,config,kind='rolling'):
        try:
            self._set(key,status='running',phase='核对原文件、适配文件与历史顺序')
            if kind=='adaptive':result=self._study_adaptive(config,key)
            elif kind=='signal':result=self._study_signal(config,key)
            elif kind=='orderbook':
                self._set(key,phase='生成明确标注的人工订单簿，并回放排队、延迟和成交')
                result=_orderbook.run_study(config)
            else:result=self._study(config,key)
            write_json(self.output/'rolling'/key/'result.json',result)
            self._set(key,status='succeeded',phase='验证完成',summary=result['dashboard_summary'])
        except Exception as error:
            self._set(key,status='failed',phase='任务失败，未生成可用结果',error=str(error))
        finally:self.work_lock.release()

    def _checked_input(self,config):
        folder=self.upload_folder(config['upload_id']);audit=json.loads((folder/'audit.json').read_text(encoding='utf-8'))
        raw=(folder/'source.csv').read_bytes();raw_hash=hashlib.sha256(raw).hexdigest()
        if raw_hash!=audit['source_sha256']:raise ValueError('原文件指纹已变化，请重新上传检查。')
        fresh=self.validator(raw,audit['symbol'])
        if not fresh['format_valid'] or fresh['counts']['zero_volume_sessions']:
            raise ValueError('文件未通过当前数据检查，或存在全日零成交量。')
        adapted=io.StringIO(newline='');csv.writer(adapted,lineterminator='\n').writerows(row for _,row in self.normalizer(raw))
        input_path=folder/'loader-input.csv';adapted_bytes=input_path.read_bytes()
        if adapted_bytes!=adapted.getvalue().encode('utf-8'):
            raise ValueError('适配文件与原文件不一致，请重新上传。')
        days,loader_audit=load_sessions(input_path,audit['symbol']);lookback=config['lookback']
        if len(days)<=lookback:raise ValueError(f'至少需要 {lookback+1} 个完整交易日，当前只有 {len(days)} 个。')
        selected=days[-(lookback+config['evaluation_days']):]
        source_hash=hashlib.sha256(adapted_bytes).hexdigest()
        return folder,audit,raw_hash,source_hash,days,selected

    def _study(self,config,key):
        folder,audit,raw_hash,source_hash,days,selected=self._checked_input(config)
        lookback=config['lookback']
        design={'symbols':[audit['symbol']],'expected_dates':[d.day.isoformat() for d in selected],
                'lookback':lookback,'fractions':[config['fraction']],'participation_rate':config['participation_rate'],
                'impact':1e-5,'risk_aversion':1e-5,
                'sources':{audit['symbol']:{'csv_member':'loader-input.csv','csv_sha256':source_hash}}}
        self._set(key,phase=f'运行 {len(selected)-lookback} 个评估日；每个目标日只使用此前数据')
        result,private,public=run_study(folder,design)
        del private,public
        for row in result['records']:
            if len(row['train_dates'])!=lookback or any(day>=row['date'] for day in row['train_dates']):
                raise ValueError('训练时间顺序校验失败。')
        states={}
        volatility=lambda d:float(np.sqrt(np.mean(np.diff(d.close)**2)/5))
        for i in range(lookback,len(selected)):
            day=selected[i];history=selected[i-lookback:i]
            states[day.day.isoformat()]={'成交量':regime(float(day.volume.sum()),[float(d.volume.sum()) for d in history]),
                                        '价格波动':regime(volatility(day),[volatility(d) for d in history])}
        grouped=[]
        for dimension in ('成交量','价格波动'):
            for level in ('低','常态','高'):
                rows=[r for r in result['records'] if states[r['date']][dimension]==level]
                grouped.extend({**r,'dimension':dimension,'regime':level} for r in summarize_rows(rows))
        summary={'available_sessions':len(days),'training_window':lookback,'evaluation_days':len(selected)-lookback,
                 'evaluation_start':result['evaluation_calendar_dates'][0],'evaluation_end':result['evaluation_calendar_dates'][-1],
                 'cases':len(result['records']),'planned':result['planned_record_count'],'completed':result['completed_record_count'],
                 'strategies':summarize_rows(result['records']),'regimes':grouped}
        result.update(title='本地数据滚动成交容量验证',source='User-supplied local CSV; origin unverified',
                      input_provenance={'upload_id':config['upload_id'],'source_sha256':raw_hash,'loader_sha256':source_hash,
                                        'origin_note':audit.get('origin_note','用户本地输入，真实性未独立核实')},
                      regime_by_date=states,dashboard_summary=summary,
                      raw_data_policy='原始输入仅保存在本机上传目录，不自动发布。',
                      generated_utc=datetime.now(timezone.utc).isoformat())
        return result

    def _study_adaptive(self,config,key):
        folder,audit,raw_hash,source_hash,days,selected=self._checked_input(config)
        self._set(key,phase=f'动态验证 {len(selected)-config["lookback"]} 个评估日；每五分钟只使用此前数据')
        result=_adaptive.run_study(days,config)
        result.update(title='成交容量风险预警与动态拆单',
                      input_provenance={'upload_id':config['upload_id'],'source_sha256':raw_hash,'loader_sha256':source_hash,
                                        'origin_note':audit.get('origin_note','用户本地输入，真实性未独立核实')},
                      generated_utc=datetime.now(timezone.utc).isoformat())
        return result

    def _study_signal(self,config,key):
        folder,audit,raw_hash,source_hash,days,selected=self._checked_input(config)
        self._set(key,phase='逐日训练信号、历史样本外验证权重，再进行目标日执行对照')
        result=_signal.run_study(days,config)
        result.update(input_provenance={'upload_id':config['upload_id'],'source_sha256':raw_hash,'loader_sha256':source_hash,
                                      'origin_note':audit.get('origin_note','用户本地输入，真实性未独立核实')},
                      generated_utc=datetime.now(timezone.utc).isoformat())
        return result

    def extension_result(self,key):
        state=self.status(key)
        if state.get('kind') not in ('signal','orderbook') or state['status']!='succeeded':
            raise ValueError('信号或订单簿任务尚未成功完成，或记录类型不正确。')
        return json.loads((self.output/'rolling'/identifier(key)/'result.json').read_text(encoding='utf-8'))

    def adaptive_result(self,key):
        state=self.status(key)
        if state.get('kind')!='adaptive' or state['status']!='succeeded':
            raise ValueError('动态任务尚未成功完成，或记录类型不正确。')
        return json.loads((self.output/'rolling'/identifier(key)/'result.json').read_text(encoding='utf-8'))

    def report(self,payload):
        if not isinstance(payload,dict) or set(payload)!={'kind','id'} or payload['kind'] not in ('core','rolling','adaptive','signal','orderbook'):
            raise ValueError('请选择已保存的基础实验或已完成的滚动任务。')
        key=identifier(payload['id']);kind=payload['kind']
        source=self.output/(key+'.json') if kind=='core' else self.output/'rolling'/key/'result.json'
        if kind!='core':
            state=self.status(key)
            if state['status']!='succeeded':raise ValueError('该任务尚未成功完成。')
            if state.get('kind','rolling')!=kind:raise ValueError('报告类型与任务不一致。')
        if not source.is_file():raise ValueError('找不到实验记录，请先运行实验。')
        raw=source.read_bytes();experiment=json.loads(raw);source_hash=hashlib.sha256(raw).hexdigest()
        page,markdown=_reports.render_report(kind,experiment,source_hash)
        report_id=uuid.uuid4().hex;folder=self.output/'reports'/report_id;folder.mkdir(parents=True)
        (folder/'report.html').write_text(page,encoding='utf-8',newline='\n')
        (folder/'report.md').write_text(markdown,encoding='utf-8',newline='\n')
        write_json(folder/'evidence.json',{'schema_version':'report-1.0','kind':kind,'source_sha256':source_hash,'experiment':experiment})
        prefix='/api/reports/'+report_id
        return {'id':report_id,'html_url':prefix+'/report.html','markdown_url':prefix+'/report.md','json_url':prefix+'/evidence.json','source_sha256':source_hash}

    def report_file(self,key,name):
        identifier(key)
        types={'report.html':'text/html; charset=utf-8','report.md':'text/plain; charset=utf-8','evidence.json':'application/json; charset=utf-8'}
        if name not in types:raise ValueError('不允许读取该文件。')
        path=self.output/'reports'/key/name
        if not path.is_file():raise ValueError('报告不存在。')
        return path,types[name]
