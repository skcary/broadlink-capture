#!/usr/bin/env python3
"""macOS capture workflow. Only user-invoked commands change local settings."""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / '.private'
RUNS = PRIVATE / 'runs'


class ToolError(Exception):
    pass


def command(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise ToolError('系统命令执行失败；请确认权限，或按 README 在系统设置中手动操作。')
    return result.stdout


def binary():
    path = shutil.which('mitmdump')
    if not path:
        raise ToolError('找不到 mitmdump。请先执行 brew install mitmproxy。')
    return path


def run_path(value=None):
    if value:
        run = Path(value).expanduser().resolve()
    else:
        marker = PRIVATE / 'current'
        if not marker.is_file():
            raise ToolError('没有当前抓包。请先执行 ./capture start。')
        run = RUNS / marker.read_text().strip()
    run = run.resolve()
    if run.parent != RUNS.resolve() or not (run / 'run.json').is_file():
        raise ToolError('抓包目录无效，必须使用本工具创建的 .private/runs/ 下的目录。')
    return run


def metadata(run):
    return json.loads((run / 'run.json').read_text())


def process_alive(run):
    pid = metadata(run).get('pid')
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        # A recycled PID must not be treated as our capture process.
        args = command(['/bin/ps', '-p', str(pid), '-o', 'args='])
        return str(run / 'ca') in args and str(ROOT / 'live_addon.py') in args
    except (ProcessLookupError, ToolError):
        return False


def proxy_settings(service, secure=False):
    flag = '-getsecurewebproxy' if secure else '-getwebproxy'
    text = command(['/usr/sbin/networksetup', flag, service])
    values = dict(line.split(': ', 1) for line in text.splitlines() if ': ' in line)
    if values.get('Enabled') not in ('Yes', 'No'):
        raise ToolError('无法读取网络服务；用 networksetup -listallnetworkservices 确认名称。')
    return values


def disable_owned(run):
    state_path = run / 'proxy-state.json'
    if not state_path.is_file():
        print('本工具没有待恢复的代理开关；若曾手动设置，请自行关闭 HTTP/HTTPS 代理。')
        return
    state = json.loads(state_path.read_text())
    service, port = state['service'], str(metadata(run)['port'])
    states = [proxy_settings(service, secure) for secure in (False, True)]
    external = False
    for flag, current in zip(('-setwebproxystate', '-setsecurewebproxystate'), states):
        if current['Enabled'] != 'Yes':
            continue
        if current.get('Server') == '127.0.0.1' and current.get('Port') == port:
            command(['/usr/sbin/networksetup', flag, service, 'off'])
        else:
            external = True
    remaining = [proxy_settings(service, secure) for secure in (False, True)]
    if any(s['Enabled'] == 'Yes' and s.get('Server') == '127.0.0.1' and s.get('Port') == port for s in remaining):
        raise ToolError('本工具的代理未成功关闭，请到系统设置中手动关闭。')
    state_path.unlink()
    print('HTTP/HTTPS 临时代理已关闭。')
    if external:
        print('其他软件更改的代理设置已保留，未覆盖。')


def enable_proxy(run, service):
    info = metadata(run)
    if not process_alive(run):
        raise ToolError('抓包进程不在运行；请先启动并等待 PROXY_READY。')
    listeners = command(['/usr/sbin/lsof', '-nP', '-a', '-p', str(info['pid']), '-iTCP:' + str(info['port']), '-sTCP:LISTEN'])
    if f'127.0.0.1:{info["port"]}' not in listeners:
        raise ToolError('本次抓包尚未监听端口，请等待 PROXY_READY。')
    if (run / 'proxy-state.json').exists():
        raise ToolError('本次代理已设置；可执行 ./capture status 检查，或先 proxy off。')
    settings = [proxy_settings(service, secure) for secure in (False, True)]
    if any(s['Enabled'] == 'Yes' or s.get('Authenticated Proxy Enabled', '0') != '0' for s in settings):
        raise ToolError('发现已有代理或代理认证配置，未覆盖；请按 README 手动设置或先处理现有代理。')
    (run / 'proxy-state.json').write_text(json.dumps({'service': service}), encoding='utf-8')
    try:
        for flag in ('-setwebproxy', '-setsecurewebproxy'):
            command(['/usr/sbin/networksetup', flag, service, '127.0.0.1', str(info['port'])])
        for flag in ('-setwebproxystate', '-setsecurewebproxystate'):
            command(['/usr/sbin/networksetup', flag, service, 'on'])
        for secure in (False, True):
            current = proxy_settings(service, secure)
            if current['Enabled'] != 'Yes' or current.get('Server') != '127.0.0.1' or current.get('Port') != str(info['port']):
                raise ToolError('代理设置未生效。')
    except Exception:
        disable_owned(run)
        raise
    print(f'{service} HTTP/HTTPS 代理已开启：127.0.0.1:{info["port"]}。请完全退出再打开微信。')


def start(args):
    exe = binary()
    if not 1024 <= args.port <= 65535:
        raise ToolError('端口必须在 1024 到 65535 之间。')
    RUNS.mkdir(parents=True, exist_ok=True)
    for state in RUNS.glob('*/proxy-state.json'):
        raise ToolError('有上次未恢复的代理，请先执行 ./capture proxy off --run ' + str(state.parent))
    with socket.socket() as check:
        try:
            check.bind(('127.0.0.1', args.port))
        except OSError:
            raise ToolError('端口已占用；请停止旧抓包，或使用 --port 指定其他端口。')
    prefix = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-')
    run = Path(tempfile.mkdtemp(prefix=prefix, dir=RUNS))
    info = {'port': args.port, 'pid': None}
    (run / 'run.json').write_text(json.dumps(info))
    (PRIVATE / 'current').write_text(run.name)
    print(f'本次目录：{run}\n本次证书：{run / "ca/mitmproxy-ca-cert.cer"}\n请等 PROXY_READY 后再开启代理。', flush=True)
    argv = [exe, '--mode', 'regular', '--listen-host', '127.0.0.1', '--listen-port', str(args.port),
            '--set', 'confdir=' + str(run / 'ca'), '--allow-hosts', r'(^|\.)ibroadlink\.com:443$',
            '--set', 'save_stream_filter=~d "^(.+[.])?ibroadlink[.]com$"',
            '--set', 'flow_detail=0', '--set', 'termlog_verbosity=error',
            '-s', str(ROOT / 'live_addon.py'), '-w', str(run / 'flows.mitm')]
    child = subprocess.Popen(argv, start_new_session=True)
    info['pid'] = child.pid
    (run / 'run.json').write_text(json.dumps(info))
    def stop_handler(signum, frame):
        raise KeyboardInterrupt
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, stop_handler)
    stopped = False
    try:
        child.wait()
    except KeyboardInterrupt:
        stopped = True
    finally:
        try:
            if (run / 'proxy-state.json').exists():
                disable_owned(run)
        finally:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    child.wait()
    print('抓包已停止。请确认系统代理关闭，然后执行 ./capture export。')
    return 0 if stopped else child.returncode


def export(args):
    run = run_path(args.run)
    if process_alive(run):
        raise ToolError('请先关闭代理，再在抓包终端按 Ctrl+C；停止后才能导出。')
    if (run / 'proxy-state.json').exists():
        raise ToolError('请先执行 ./capture proxy off。')
    source = run / 'flows.mitm'
    if not source.is_file() or source.stat().st_size == 0:
        raise ToolError('抓包文件不存在或为空；请确认代理开启且 vendor_http_responses 计数增长。')
    destination = Path(args.output).expanduser().resolve() if args.output else ROOT / 'exports' / run.name
    if destination == PRIVATE.resolve() or PRIVATE.resolve() in destination.parents:
        raise ToolError('导出目录不能放在 .private 内，以免清理抓包时误删 JSON。')
    if destination.exists():
        raise ToolError('导出目录已存在，请使用新的 --output 路径。')
    result_path = run / 'export-result.json'
    result_path.unlink(missing_ok=True)
    env = dict(os.environ, BROADLINK_CAPTURE_RUN=str(run), BROADLINK_EXPORT_OUTPUT=str(destination))
    result = subprocess.run([binary(), '--no-server', '--set', 'confdir=' + str(run / 'ca'),
                             '--set', 'termlog_verbosity=error', '--set', 'flow_detail=0',
                             '-s', str(ROOT / 'export_addon.py')], env=env)
    if result.returncode or not result_path.is_file() or not json.loads(result_path.read_text()).get('ok'):
        return 2
    print('请自行将两份 JSON 放到 HA 的 config/cloudthink_broadlink/；不要发到聊天或提交到 Git。')
    return 0


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description='macOS 全屋智控抓包与离线导出工具')
    commands = parser.add_subparsers(dest='action', required=True)
    p = commands.add_parser('start', help='新建一轮抓包；不自动开代理、不自动信任证书')
    p.add_argument('--port', type=int, default=8080)
    p = commands.add_parser('proxy', help='开启或关闭本工具的临时代理')
    p.add_argument('state', choices=('on', 'off'))
    p.add_argument('--service', default='Wi-Fi')
    p.add_argument('--run')
    p = commands.add_parser('export', help='停止抓包后离线导出两份 JSON')
    p.add_argument('--run')
    p.add_argument('--output')
    p = commands.add_parser('status', help='显示当前抓包和系统代理状态，不显示凭证')
    p.add_argument('--run')
    p.add_argument('--service', default='Wi-Fi')
    p = commands.add_parser('cleanup', help='手动删除本轮原始抓包、CA 私钥及元数据；保留导出的 JSON')
    p.add_argument('--run')
    p.add_argument('--yes', action='store_true')
    args = parser.parse_args()
    if platform.system() != 'Darwin':
        raise ToolError('本工具的启动和代理管理仅支持 macOS。')
    if args.action == 'start':
        return start(args)
    if args.action == 'export':
        return export(args)
    run = run_path(args.run)
    if args.action == 'proxy':
        if args.state == 'on':
            enable_proxy(run, args.service)
        else:
            disable_owned(run)
    elif args.action == 'status':
        print(f'本次目录：{run}\n抓包进程运行：{process_alive(run)}\n端口：{metadata(run)["port"]}')
        state = run / 'proxy-state.json'
        service = json.loads(state.read_text())['service'] if state.is_file() else args.service
        for label, secure in (('HTTP', False), ('HTTPS', True)):
            values = proxy_settings(service, secure)
            print(f'{service} {label}：{values["Enabled"]}；服务器 {values.get("Server", "")}；端口 {values.get("Port", "")}')
    elif args.action == 'cleanup':
        if process_alive(run) or (run / 'proxy-state.json').exists():
            raise ToolError('请先关闭代理并停止抓包，再清理。')
        print('先在钥匙串访问中删除本轮导入的 mitmproxy 证书。')
        if not args.yes and input('确认已删除证书，并删除本轮原始抓包、CA 私钥及元数据？[y/N] ').lower() != 'y':
            print('已取消。')
            return 0
        shutil.rmtree(run)
        marker = PRIVATE / 'current'
        if marker.is_file() and marker.read_text().strip() == run.name:
            marker.unlink()
        print('本轮原始抓包与 CA 文件已删除；导出的 JSON 保留。')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ToolError as exc:
        print(f'错误：{exc}', file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f'操作失败（{type(exc).__name__}）。检查文件权限及依赖；不要分享原始凭证或抓包。', file=sys.stderr)
        sys.exit(2)
