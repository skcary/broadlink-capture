import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cli


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        (self.run / 'run.json').write_text(json.dumps({'pid': 123, 'port': 8080}))

    def test_no_process_no_network_settings_changed(self):
        with patch.object(cli, 'process_alive', return_value=False), patch.object(cli, 'command') as cmd:
            with self.assertRaises(cli.ToolError):
                cli.enable_proxy(self.run, 'Wi-Fi')
            cmd.assert_not_called()

    def test_existing_proxy_not_overwritten(self):
        settings = {'Enabled': 'Yes', 'Server': 'existing.example', 'Port': '1234', 'Authenticated Proxy Enabled': '0'}
        with patch.object(cli, 'process_alive', return_value=True), patch.object(cli, 'command', return_value='127.0.0.1:8080') as cmd, patch.object(cli, 'proxy_settings', return_value=settings):
            with self.assertRaises(cli.ToolError):
                cli.enable_proxy(self.run, 'Wi-Fi')
            self.assertEqual(cmd.call_count, 1)  # lsof only
            self.assertFalse((self.run / 'proxy-state.json').exists())

    def test_changed_proxy_not_disabled(self):
        (self.run / 'proxy-state.json').write_text(json.dumps({'service': 'Wi-Fi'}))
        settings = {'Enabled': 'Yes', 'Server': 'new.example', 'Port': '9999'}
        with patch.object(cli, 'proxy_settings', return_value=settings), patch.object(cli, 'command') as cmd:
            cli.disable_owned(self.run)
            cmd.assert_not_called()
            self.assertFalse((self.run / 'proxy-state.json').exists())

    def test_external_http_preserved_owned_https_disabled(self):
        (self.run / 'proxy-state.json').write_text(json.dumps({'service': 'Wi-Fi'}))
        external = {'Enabled': 'Yes', 'Server': 'other.example', 'Port': '9000'}
        owned = {'Enabled': 'Yes', 'Server': '127.0.0.1', 'Port': '8080'}
        disabled = dict(owned, Enabled='No')
        with patch.object(cli, 'proxy_settings', side_effect=[external, owned, external, disabled]), patch.object(cli, 'command') as cmd:
            cli.disable_owned(self.run)
            cmd.assert_called_once_with(['/usr/sbin/networksetup', '-setsecurewebproxystate', 'Wi-Fi', 'off'])
            self.assertFalse((self.run / 'proxy-state.json').exists())

    def test_partial_enable_attempts_rollback(self):
        settings = {'Enabled': 'No', 'Server': '', 'Port': '0', 'Authenticated Proxy Enabled': '0'}
        def fake_command(args):
            if '-setwebproxy' in args:
                raise cli.ToolError('synthetic failure')
            return '127.0.0.1:8080'
        with patch.object(cli, 'process_alive', return_value=True), patch.object(cli, 'proxy_settings', return_value=settings), patch.object(cli, 'command', side_effect=fake_command), patch.object(cli, 'disable_owned') as rollback:
            with self.assertRaises(cli.ToolError):
                cli.enable_proxy(self.run, 'Wi-Fi')
            rollback.assert_called_once_with(self.run)


if __name__ == '__main__':
    unittest.main()
