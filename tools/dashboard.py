"""Local interactive front end for the unchanged execution model; no new dependencies."""
import argparse
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import uuid

from execution_lab.config import ExecutionConfig
from execution_lab.schedule import make_twap, make_ac
from execution_lab.simulation import run_paired
from execution_lab.metrics import summarize


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


def make_server(port, output):
    source = Path(__file__).resolve().parents[1]
    output = Path(output)
    if not output.is_absolute():
        raise ValueError('输出目录必须是绝对路径。')
    output = output.resolve()
    if output == source or source in output.parents:
        raise ValueError('输出目录必须位于仓库之外。')
    output.mkdir(parents=True, exist_ok=True)
    gate = threading.Lock()

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
            if self.path == '/':
                self.send(200, Path(__file__).with_name('dashboard.html').read_bytes(), 'text/html; charset=utf-8')
            else:
                self.send(404, {'error': '页面不存在。'})

        def do_POST(self):
            if self.path != '/api/run':
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
                if not 0 < length <= 8192:
                    raise ValueError('参数为空或过长。')
                result = run_experiment(json.loads(self.rfile.read(length)))
                # A new name preserves earlier experiments; files never enter the source tree.
                target = output / (uuid.uuid4().hex + '.json')
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
    args = parser.parse_args()
    try:
        server = make_server(args.port, args.output)
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
