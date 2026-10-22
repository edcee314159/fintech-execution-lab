"""Local interactive front end for the unchanged execution model; no new dependencies."""
import argparse
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import uuid
import importlib.util
import base64
import csv
import io
import math
import re
import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, parse_qs
import numpy as np

from execution_lab.config import ExecutionConfig
from execution_lab.schedule import make_twap, make_ac
from execution_lab.simulation import run_paired
from execution_lab.metrics import summarize

_workflow_spec = importlib.util.spec_from_file_location('execution_dashboard_workflows', Path(__file__).with_name('workflows.py'))
workflows = importlib.util.module_from_spec(_workflow_spec)
_workflow_spec.loader.exec_module(workflows)


def run_experiment(data):
    c = ExecutionConfig.from_dict(data)
    if c.intervals > 120 or c.trials > 2000 or c.trials * (c.intervals + 1) > 120000:
        raise ValueError('面板上限：120 个时段、2000 次模拟，且模拟次数 × (时段数 + 1) 不超过 120000。')
    schedules = {'twap': make_twap(c), 'ac_simplified': make_ac(c)}
    experiment = run_paired(c, schedules)
    return {'schema_version': 'dashboard-1.0', 'config': c.to_dict(),
            'summary': summarize(experiment),
            'schedules': {name: {'quantities': s.quantities.tolist(), 'inventory': s.inventory.tolist()}
                          for name, s in schedules.items()},
            'assumptions': '基础模型只研究卖单，假设计划全部成交；不验证真实成交量、排队或实盘收益。'}



def replay_catalog():
    root = Path(__file__).resolve().parents[1] / 'results' / 'real-volume'
    data = json.loads((root / 'results.json').read_text(encoding='utf-8'))
    cases = []
    for r in data['records']:
        case = {key: r[key] for key in ('id', 'symbol', 'date', 'predictor', 'planner', 'order_fraction_adv', 'quantity', 'planning_feasible')}
        case.update(residual=r['replay']['residual'] if r['replay'] else None,
                    complete=r['replay']['complete'] if r['replay'] else None,
                    participation_rate=data['design']['participation_rate'])
        cases.append(case)
    return cases


def replay_case(case_id):
    # Resolve identifiers against the fixed catalog, never as user-supplied paths.
    case = next((c for c in replay_catalog() if c['id'] == case_id), None)
    if case is None:
        raise ValueError('回放情形不存在。')
    result = {'case': case, 'available': case['planning_feasible'], 'interval_minutes': 5}
    if not result['available']:
        return result
    root = Path(__file__).resolve().parents[1] / 'results' / 'real-volume'
    with np.load(root / 'derived-schedules.npz', allow_pickle=False) as data:
        planned, fills, remaining = (data[case_id + '_' + key] for key in ('planned', 'fills', 'remaining'))
    q = case['quantity']
    if (planned.shape != (78,) or fills.shape != (78,) or remaining.shape != (79,)
            or any(not np.issubdtype(a.dtype, np.integer) or np.any(a < 0) for a in (planned, fills, remaining))):
        raise ValueError('已保存回放数组的格式或数量不正确。')
    released = np.r_[0, np.cumsum(planned)]
    executed = np.r_[0, np.cumsum(fills)]
    backlog = released - executed
    if (int(planned.sum()) != q or np.any(backlog < 0) or not np.array_equal(remaining, q - executed)
            or int(remaining[-1]) != case['residual'] or (case['complete'] != (int(remaining[-1]) == 0))):
        raise ValueError('已保存回放记录未通过数量核对。')
    result.update(planned=planned.tolist(), fills=fills.tolist(), remaining=remaining.tolist(),
                  cumulative_planned=released.tolist(), cumulative_filled=executed.tolist(),
                  backlog=backlog.tolist(), capacity_limited=(backlog[1:] > 0).tolist())
    return result



MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _csv_records(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_UPLOAD_BYTES:
        raise ValueError('CSV 文件须非空且不超过 5 MiB。')
    try:
        text = raw.decode('utf-8-sig')
        reader = csv.reader(io.StringIO(text, newline=''), strict=True)
        records = [(reader.line_num, [v.strip() for v in row]) for row in reader if row and any(v.strip() for v in row)]
    except (UnicodeError, csv.Error) as error:
        raise ValueError('请使用 UTF-8 编码、逗号分隔的 CSV。') from error
    if not records or len(records) > 100001 or len(records[0][1]) != 6:
        raise ValueError('CSV 需要六列，且最多 100000 条数据行。')
    required = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    header = [v.lower().replace('datetime', 'timestamp') for v in records[0][1]]
    if any(v in required for v in header):
        if len(set(header)) != 6 or set(header) != set(required):
            raise ValueError('表头必须为 timestamp,open,high,low,close,volume，可调整列顺序。')
        order = [header.index(v) for v in required]
        records = [(line, [row[i] for i in order] if len(row) == 6 else row) for line, row in records[1:]]
    if not records or len(records) > 100000:
        raise ValueError('CSV 需要 1 至 100000 条数据行。')
    return records


def audit_csv(raw, symbol):
    if not isinstance(symbol, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9._-]{0,11}', symbol):
        raise ValueError('标的代码须为 1 至 12 位英文字母、数字、点、横线或下划线，并以字母开头。')
    records = _csv_records(raw)
    keys = ('invalid_timestamp', 'invalid_columns', 'invalid_ohlc', 'invalid_volume', 'invalid_session_date',
            'exact_duplicates', 'conflicting_duplicates', 'out_of_order', 'outside_session',
            'missing_minutes', 'volume_spikes', 'zero_volume_sessions')
    counts = dict.fromkeys(keys, 0)
    examples, groups, seen, invalid_lines = [], {}, {}, set()
    previous = None

    def issue(code, line, message, fatal=False):
        counts[code] += 1
        if fatal:
            invalid_lines.add(line)
        if len(examples) < 20:
            examples.append({'code': code, 'line': line, 'message': message})

    for line, row in records:
        if len(row) != 6:
            issue('invalid_columns', line, '该行不是六列。', True); continue
        try:
            t = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            issue('invalid_timestamp', line, '时间须为 YYYY-MM-DD HH:MM:SS，且已转换为纽约本地时间。', True); continue
        minute = t.hour * 60 + t.minute
        inside = 570 <= minute < 960
        if not inside:
            counts['outside_session'] += 1
        group = groups.setdefault(t.date(), {'values': {}, 'lines': {}, 'bad': False, 'line': line}) if inside else None
        if previous is not None and t < previous:
            issue('out_of_order', line, '时间早于上一条记录；请核实顺序，本工具不会自动排序。', True)
        previous = t
        if t.second != 0:
            issue('invalid_timestamp', line, '一分钟数据的秒数须为 00。', True)
            if group: group['bad'] = True
            continue
        if t.weekday() > 4 and inside:
            issue('invalid_session_date', line, '周末的常规时段记录不纳入当前美股数据格式。', True)
            group['bad'] = True; continue
        bad = False
        try:
            o, h, l, c = map(float, row[1:5])
            if not all(math.isfinite(v) for v in (o, h, l, c)) or not 0 < l <= min(o, c) <= max(o, c) <= h:
                raise ValueError()
        except ValueError:
            issue('invalid_ohlc', line, '价格须有限且为正，并满足最低价不高于开收盘价、最高价不低于开收盘价。', True)
            bad = True
        try:
            v = Decimal(row[5])
            if not v.is_finite() or not 0 <= v <= 10**12 or v != v.to_integral_value():
                raise ValueError()
        except (ValueError, InvalidOperation):
            issue('invalid_volume', line, '成交量须为 0 至 1e12 的有限整数，不替换负数、非整数或异常数值。', True)
            bad = True
        if bad:
            if group: group['bad'] = True
            continue
        values = (o, h, l, c, int(v))
        if t in seen:
            if seen[t] == values:
                issue('exact_duplicates', line, '该时点与前一份记录完全相同，原始文件保留，已有读取器按其规则去重。')
            else:
                issue('conflicting_duplicates', line, '相同时点存在不同价格或成交量；不能确定哪条正确。', True)
                if group: group['bad'] = True
            continue
        seen[t] = values
        if group:
            group['values'][minute] = values
            group['lines'][minute] = line

    sessions = []
    for day, group in sorted(groups.items()):
        values = group['values']
        missing = 390 - len(values)
        counts['missing_minutes'] += missing
        reasons = []
        if missing:
            reasons.append('missing_minutes')
            if len(examples) < 20:
                examples.append({'code': 'missing_minutes', 'line': group['line'], 'message': f'{day.isoformat()} 缺少 {missing} 个有效分钟，不补零或插值。'})
        if group['bad']:
            reasons.append('invalid_rows')
        volumes = [a[4] for a in values.values()]
        positive = [v for v in volumes if v > 0]
        if positive:
            median = float(np.median(positive))
            spike_minutes = [minute for minute, record in values.items() if record[4] > 20 * median]
            counts['volume_spikes'] += len(spike_minutes)
            for minute in spike_minutes:
                if len(examples) < 20:
                    examples.append({'code': 'volume_spikes', 'line': group['lines'][minute],
                                     'message': '该分钟成交量超过当日正成交量中位数的 20 倍；仅作复核提示，不删除。'})
        if not reasons and not any(volumes):
            counts['zero_volume_sessions'] += 1
        sessions.append({'date': day.isoformat(), 'valid_minutes': len(values), 'missing_minutes': missing,
                         'complete': not reasons, 'reasons': reasons})
    dates = [day['date'] for day in sessions if day['complete']]
    counts['invalid_rows'] = len(invalid_lines)
    valid = bool(dates) and not (counts['invalid_rows'] or counts['missing_minutes'])
    return {'schema_version': 'csv-audit-1.0', 'symbol': symbol.upper(), 'input_rows': len(records),
            'timezone': 'America/New_York', 'complete_sessions': len(dates), 'usable_dates': dates,
            'format_valid': valid, 'ready_for_pilot': valid and len(dates) >= 6 and counts['zero_volume_sessions'] == 0,
            'counts': counts, 'sessions': sessions, 'examples': examples,
            'scope': '单标的一分钟美股常规时段，纽约墙上时间 09:30 至 15:59；不识别整日缺失、节假日或提前收盘，不证明数据真实或授权。',
            'policy': '保留原始文件，不补缺失、不自动排序、不替换异常值；六个完整日只是五日回看加一日评估的最低数据量。'}


def store_upload(payload, output):
    if not isinstance(payload, dict) or set(payload) != {'symbol', 'timezone', 'csv_base64'}:
        raise ValueError('上传参数须包含 symbol、timezone 和 csv_base64。')
    if payload['timezone'] != 'America/New_York':
        raise ValueError('请先确认时间已经转换为纽约本地时间；本工具不自动转换时区。')
    try:
        raw = base64.b64decode(payload['csv_base64'], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError('上传文件编码不正确。') from error
    report = audit_csv(raw, payload['symbol'])
    upload_id = uuid.uuid4().hex
    folder = output / 'uploads' / upload_id
    folder.mkdir(parents=True)
    (folder / 'source.csv').write_bytes(raw)
    report.update(upload_id=upload_id, source_sha256=hashlib.sha256(raw).hexdigest())
    if report['format_valid']:
        adapted = io.StringIO(newline='')
        csv.writer(adapted, lineterminator='\n').writerows(row for _, row in _csv_records(raw))
        (folder / 'loader-input.csv').write_text(adapted.getvalue(), encoding='utf-8', newline='\n')
        from execution_volume_validation.data import load_sessions
        days, audit = load_sessions(folder / 'loader-input.csv', report['symbol'])
        if audit['accepted_sessions'] != report['usable_dates']:
            raise ValueError('与现有读取器的核对结果不一致。')
        report['loader_audit'] = audit
    (folder / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    return report


def make_server(port, output, uploads_from=None):
    source = Path(__file__).resolve().parents[1]
    output = Path(output)
    if not output.is_absolute():
        raise ValueError('输出目录必须是绝对路径。')
    output = output.resolve()
    if output == source or source in output.parents:
        raise ValueError('输出目录必须位于仓库之外。')
    output.mkdir(parents=True, exist_ok=True)
    gate = threading.Lock()
    service = workflows.WorkflowService(output, uploads_from, validator=audit_csv, normalizer=_csv_records)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass

        def send(self, status, payload, kind='application/json; charset=utf-8'):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == '/' and not url.query:
                self.send(200, Path(__file__).with_name('dashboard.html').read_bytes(), 'text/html; charset=utf-8')
            elif url.path in ('/replay.js', '/upload.js', '/workflows.js', '/adaptive.js', '/extensions.js', '/budget_pairs.js', '/execution_safety.js') and not url.query:
                self.send(200, Path(__file__).with_name(url.path[1:]).read_bytes(), 'text/javascript; charset=utf-8')
            elif url.path == '/api/uploads' and not url.query:
                self.send(200, service.list_uploads())
            elif url.path.startswith('/api/extensions/') and not url.query:
                try:
                    self.send(200, service.extension_result(url.path[len('/api/extensions/'):]))
                except ValueError as error:
                    self.send(400, {'error': str(error)})
            elif url.path.startswith('/api/adaptive/') and not url.query:
                try:
                    self.send(200, service.adaptive_result(url.path[len('/api/adaptive/'):]))
                except ValueError as error:
                    self.send(400, {'error': str(error)})
            elif url.path.startswith('/api/rolling/') and not url.query:
                try:
                    self.send(200, service.status(url.path[len('/api/rolling/'):]))
                except ValueError as error:
                    self.send(400, {'error': str(error)})
            elif url.path.startswith('/api/reports/') and not url.query:
                try:
                    parts = url.path.split('/')
                    if len(parts) != 5:
                        raise ValueError('报告地址不正确。')
                    path, kind = service.report_file(parts[3], parts[4])
                    self.send(200, path.read_bytes(), kind)
                except ValueError as error:
                    self.send(400, {'error': str(error)})
            elif url.path == '/api/replay-cases' and not url.query:
                self.send(200, replay_catalog())
            elif url.path == '/api/replay':
                try:
                    query = parse_qs(url.query)
                    if set(query) != {'id'} or len(query['id']) != 1:
                        raise ValueError('请选择一个回放情形。')
                    self.send(200, replay_case(query['id'][0]))
                except ValueError as error:
                    self.send(400, {'error': str(error)})
            else:
                self.send(404, {'error': '页面不存在。'})

        def do_POST(self):
            if self.path not in ('/api/run', '/api/upload', '/api/rolling', '/api/report', '/api/adaptive', '/api/signal', '/api/orderbook', '/api/budget', '/api/pairs', '/api/recovery', '/api/marketguard'):
                self.send(404, {'error': '接口不存在。'}); return
            hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            origin = self.headers.get('Origin')
            if self.headers.get('Host') not in hosts or (origin is not None and origin not in {'http://' + h for h in hosts}):
                self.send(403, {'error': '仅允许从本地面板运行。'}); return
            if self.headers.get_content_type() != 'application/json':
                self.send(415, {'error': '请发送 JSON 参数。'}); return
            if not gate.acquire(blocking=False):
                self.send(429, {'error': '已有实验正在运行，请稍后重试。'}); return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                limit = MAX_UPLOAD_BYTES * 4 // 3 + 8192 if self.path == '/api/upload' else 8192
                if not 0 < length <= limit:
                    raise ValueError('参数为空或过长。')
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError('文件传输不完整，请重试。')
                payload = json.loads(body)
                if self.path == '/api/upload':
                    result = store_upload(payload, output)
                elif self.path == '/api/signal':
                    result = service.start_signal(payload)
                elif self.path in ('/api/recovery','/api/marketguard'):
                    result = service.start_safety(payload,self.path.removeprefix('/api/'))
                elif self.path == '/api/budget':
                    result = service.start_budget(payload)
                elif self.path == '/api/pairs':
                    result = service.start_pairs(payload)
                elif self.path == '/api/orderbook':
                    result = service.start_orderbook(payload)
                elif self.path in ('/api/rolling', '/api/adaptive'):
                    result = service.start(payload, adaptive=self.path == '/api/adaptive')
                elif self.path == '/api/report':
                    result = service.report(payload)
                else:
                    result = run_experiment(payload)
                    result['experiment_id'] = uuid.uuid4().hex
                    target = output / (result['experiment_id'] + '.json')
                    text = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
                    target.write_text(text, encoding='utf-8', newline='\n')

                self.send(200, result)
            except (ValueError, TypeError, OverflowError) as error:
                self.send(400, {'error': str(error)})
            except Exception:
                self.send(500, {'error': '实验运行失败，请检查本地终端及输出目录。'})
                raise
            finally:
                gate.release()

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Absolute experiment output directory outside source')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--uploads-from', type=Path, help='Optional previous local output directory for existing uploads')
    args = parser.parse_args()
    try:
        server = make_server(args.port, args.output, args.uploads_from)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f'Local dashboard: http://127.0.0.1:{server.server_port}', flush=True)
    print(f'Experiment output: {args.output.resolve()}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
