import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capture_core import ExportError, HEADERS, choose_pair, inspect_flow, vendor_host, write_pair


def flow(session='synthetic-session', family='synthetic-family', cookie='synthetic-cookie',
         discovery=True, status=200, response_name=None, devices=None):
    headers = {key: 'synthetic-' + key for key in HEADERS}
    headers.update(loginsession=session, familyid=family)
    body = {'header': {'name': 'DiscoverAppliancesRequest' if discovery else 'ReportStateRequest'}, 'payload': {}}
    if cookie is not None:
        body['payload']['cookie'] = cookie
    device = {'applianceId': 'synthetic-device', 'additionalApplianceDetails': {'opaque': 'keep-exactly'}, 'roomName': '测试房间'}
    result = {'header': {'name': response_name or ('DiscoverAppliancesResponse' if discovery else 'ReportStateConfirmation')}, 'payload': {}}
    if discovery:
        result['payload']['discoveredAppliances'] = [device] if devices is None else devices
    request = SimpleNamespace(method='POST', host='synthetic.ibroadlink.com', scheme='https', port=443,
                              path='/appfront/v1/houseproxy/v1/dueros', headers=headers, json=lambda: body)
    return SimpleNamespace(request=request, response=SimpleNamespace(status_code=status, json=lambda: result))


class ExportTests(unittest.TestCase):
    def test_valid_export_preserves_device_details(self):
        record = inspect_flow(flow())
        session, devices = choose_pair([record])
        self.assertEqual(session['headers']['loginsession'], 'synthetic-session')
        self.assertEqual(devices[0]['additionalApplianceDetails'], {'opaque': 'keep-exactly'})

    def test_http_and_protocol_errors_rejected(self):
        self.assertIsNone(inspect_flow(flow(status=403)))
        self.assertIsNone(inspect_flow(flow(response_name='ErrorResponse')))

    def test_later_401_prevents_export_of_previously_successful_session(self):
        with self.assertRaises(ExportError):
            choose_pair([inspect_flow(flow()), inspect_flow(flow(status=401))])

    def test_success_after_401_can_recover(self):
        session, _ = choose_pair([inspect_flow(flow(status=401)), inspect_flow(flow())])
        self.assertEqual(session['headers']['loginsession'], 'synthetic-session')

    def test_mixed_families_rejected(self):
        with self.assertRaises(ExportError):
            choose_pair([inspect_flow(flow()), inspect_flow(flow(family='another'))])

    def test_latest_login_used_when_discovered(self):
        pair = choose_pair([inspect_flow(flow(session='old')), inspect_flow(flow(session='new'))])
        self.assertEqual(pair[0]['headers']['loginsession'], 'new')

    def test_new_login_without_discovery_does_not_export_old_pair(self):
        with self.assertRaises(ExportError):
            choose_pair([inspect_flow(flow(session='old')), inspect_flow(flow(session='new', discovery=False))])

    def test_cookie_fallback_requires_same_session(self):
        discovery = inspect_flow(flow(cookie=None))
        pair = choose_pair([inspect_flow(flow(discovery=False)), discovery])
        self.assertEqual(pair[0]['cookie'], 'synthetic-cookie')
        with self.assertRaises(ExportError):
            choose_pair([inspect_flow(flow(session='old', discovery=False)), discovery])

    def test_ambiguous_cookie_rejected(self):
        with self.assertRaises(ExportError):
            choose_pair([inspect_flow(flow(cookie='a', discovery=False)), inspect_flow(flow(cookie='b', discovery=False)), inspect_flow(flow(cookie=None))])

    def test_duplicate_ids_and_empty_discovery_rejected(self):
        device = {'applianceId': 'duplicate', 'additionalApplianceDetails': {}}
        for devices in ([device, device], []):
            with self.assertRaises(ExportError):
                choose_pair([inspect_flow(flow(devices=devices))])

    def test_partial_credentials_and_wrong_endpoint_rejected(self):
        candidate = flow()
        candidate.request.headers.pop('userid')
        self.assertIsNone(inspect_flow(candidate))
        candidate = flow()
        candidate.request.path = '/unrelated'
        self.assertIsNone(inspect_flow(candidate))

    def test_vendor_boundary(self):
        self.assertTrue(vendor_host('test.ibroadlink.com'))
        self.assertFalse(vendor_host('notibroadlink.com'))
        self.assertFalse(vendor_host('ibroadlink.com.attacker.example'))

    def test_atomic_pair_and_permissions_no_overwrite(self):
        pair = choose_pair([inspect_flow(flow())])
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'export'
            write_pair(output, *pair)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            for name, expected in zip(('session.json', 'devices.json'), pair):
                path = output / name
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads(path.read_text()), expected)
            with self.assertRaises(ExportError):
                write_pair(output, *pair)

    def test_empty_capture(self):
        with self.assertRaises(ExportError):
            choose_pair([])


if __name__ == '__main__':
    unittest.main()
