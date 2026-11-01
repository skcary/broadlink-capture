"""Run inside the mitmdump binary so no pip mitmproxy dependency is needed."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_core import ExportError, choose_pair, inspect_flow, write_pair


class OfflineCaptureExport:
    async def running(self):
        from mitmproxy import ctx, http, io
        run = Path(os.environ['BROADLINK_CAPTURE_RUN'])
        result = {'ok': False}
        try:
            records, total = [], 0
            with (run / 'flows.mitm').open('rb') as stream:
                for flow in io.FlowReader(stream).stream():
                    if isinstance(flow, http.HTTPFlow):
                        total += 1
                        record = inspect_flow(flow)
                        if record:
                            records.append(record)
            print(f'HTTP 记录：{total}；可识别目标记录（含鉴权失败）：{len(records)}', flush=True)
            session, devices = choose_pair(records)
            output = Path(os.environ['BROADLINK_EXPORT_OUTPUT'])
            write_pair(output, session, devices)
            print(f'导出成功：{output}\n文件：session.json、devices.json；设备数：{len(devices)}；权限：600', flush=True)
            result = {'ok': True, 'devices': len(devices)}
        except ExportError as exc:
            print(f'未导出：{exc}', flush=True)
        except Exception as exc:
            print(f'未完成导出（{type(exc).__name__}），请不要分享原始抓包或异常原文。', flush=True)
        finally:
            (run / 'export-result.json').write_text(json.dumps(result), encoding='utf-8')
            ctx.master.shutdown()


addons = [OfflineCaptureExport()]
