"""Protocol parsing and local export. No networking or credential logging."""
import json
import os
import shutil
import tempfile
from pathlib import Path

HEADERS = ('loginsession', 'userid', 'familyid', 'licenseid', 'activationcode', 'companyid')
ENDPOINT = '/appfront/v1/houseproxy/v1/dueros'


class ExportError(Exception):
    """Only fixed, non-sensitive messages should be used here."""


def vendor_host(host):
    host = host.lower().rstrip('.')
    return host == 'ibroadlink.com' or host.endswith('.ibroadlink.com')


def inspect_flow(flow):
    req, response = flow.request, flow.response
    if not vendor_host(req.host) or req.scheme != 'https' or req.path.split('?', 1)[0] != ENDPOINT:
        return None
    if req.method != 'POST' or response is None:
        return None
    headers = {key: req.headers.get(key, '') for key in HEADERS}
    if not all(isinstance(value, str) and value for value in headers.values()):
        return None
    authority = req.host if req.port == 443 else f'{req.host}:{req.port}'
    url = f'https://{authority}{ENDPOINT}'
    identity = (url, *(headers[key] for key in HEADERS))
    family = (url, *(headers[key] for key in HEADERS if key != 'loginsession'))
    if response.status_code == 401:
        return {'identity': identity, 'family': family, 'session': None, 'devices': None, 'auth_failed': True}
    if not 200 <= response.status_code < 300:
        return None
    try:
        body, result = req.json(), response.json()
    except (ValueError, TypeError):
        return None
    if not isinstance(body, dict) or not isinstance(result, dict):
        return None
    rh, payload = result.get('header'), body.get('payload')
    if not isinstance(rh, dict) or not isinstance(payload, dict):
        return None
    name = rh.get('name')
    if not isinstance(name, str) or not name or any(word in name.lower() for word in ('error', 'exception')):
        return None
    session = None
    cookie = payload.get('cookie')
    if isinstance(cookie, str) and cookie:
        headers['Content-Type'] = 'application/json'
        for optional in ('Referer', 'xweb_xhr'):
            if req.headers.get(optional):
                headers[optional] = req.headers[optional]
        session = {'url': url, 'headers': headers, 'cookie': cookie}
    devices = None
    header = body.get('header')
    if isinstance(header, dict) and header.get('name') == 'DiscoverAppliancesRequest':
        rp = result.get('payload')
        items = rp.get('discoveredAppliances') if isinstance(rp, dict) else None
        if isinstance(items, list) and items and all(
            isinstance(item, dict)
            and isinstance(item.get('applianceId'), str) and item['applianceId']
            and isinstance(item.get('additionalApplianceDetails'), dict)
            for item in items
        ):
            ids = [item['applianceId'] for item in items]
            if len(ids) == len(set(ids)):
                devices = items
    return {'identity': identity, 'family': family, 'session': session, 'devices': devices}


def choose_pair(records):
    if not records:
        raise ExportError('未找到成功且鉴权头完整的 houseproxy 请求；请查看抓包计数及 README 排错。')
    if len({r['family'] for r in records}) != 1:
        raise ExportError('检测到多个家庭、账号或服务实例，请新建抓包，一次只选择一个家庭。')
    latest = records[-1]['identity']
    matching = [r for r in records if r['identity'] == latest]
    if matching[-1].get('auth_failed'):
        raise ExportError('最新会话最后出现 HTTP 401，未导出早先成功记录。请重新登录并刷新设备列表。')
    discoveries = [r for r in matching if r['devices'] is not None]
    if not discoveries:
        raise ExportError('最新会话没有有效设备发现响应。请重新打开小程序并刷新全屋设备列表后再抓取。')
    discovery = discoveries[-1]
    session = discovery['session']
    if session is None:
        sessions = [r['session'] for r in matching if r['session'] is not None]
        if len({s['cookie'] for s in sessions}) != 1:
            raise ExportError('设备发现请求缺少 cookie，且无法唯一匹配同一会话的设备 cookie；请重新抓取。')
        session = sessions[-1]
    return session, discovery['devices']


def write_pair(destination, session, devices):
    destination = Path(destination)
    if destination.exists():
        raise ExportError('导出目录已存在；为防止覆盖，请指定一个新的 --output 目录。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.pending-', dir=destination.parent))
    try:
        for name, value in (('session.json', session), ('devices.json', devices)):
            path = temporary / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
        # Publish both files together only after both writes succeed.
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
