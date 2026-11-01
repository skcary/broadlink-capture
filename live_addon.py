"""Show readiness and counters, without displaying URLs, headers or bodies."""
from collections import Counter


class Counters:
    def __init__(self):
        self.counts = Counter()

    def running(self):
        print('PROXY_READY：代理已就绪。保持本终端运行；现在可在另一终端执行 ./capture proxy on。', flush=True)

    def bump(self, name):
        self.counts[name] += 1
        value = self.counts[name]
        if value in (1, 5, 20, 100) or value % 200 == 0:
            print(f'COUNT {name}={value}', flush=True)

    def client_connected(self, client):
        self.bump('local_connections')

    @staticmethod
    def vendor(flow):
        host = flow.request.host.lower().rstrip('.')
        return host == 'ibroadlink.com' or host.endswith('.ibroadlink.com')

    def http_connect(self, flow):
        self.bump('vendor_connect' if self.vendor(flow) else 'other_connect')

    def request(self, flow):
        if self.vendor(flow):
            self.bump('vendor_http_requests')

    def response(self, flow):
        if self.vendor(flow):
            self.bump('vendor_http_responses')

    def tls_failed_client(self, data):
        self.bump('client_tls_failures')

    def tls_failed_server(self, data):
        self.bump('server_tls_failures')

    def server_connect_error(self, data):
        self.bump('upstream_connect_failures')

    def done(self):
        print('TOTAL ' + ', '.join(f'{key}={value}' for key, value in sorted(self.counts.items())), flush=True)


addons = [Counters()]
