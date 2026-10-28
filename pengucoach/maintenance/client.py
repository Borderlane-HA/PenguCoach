"""Same-host application bridge; no TCP/Docker socket and no user-supplied URL."""
import json
from pathlib import Path

import httpx

SOCKET = '/run/pengucoach-maintenance/control.sock'


def client(timeout=15):
    return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=SOCKET),
                            base_url='http://maintenance',timeout=httpx.Timeout(timeout,connect=2),trust_env=False)


async def request(method, path, *, json=None, content=None, timeout=15):
    async with (client(timeout) if timeout != 15 else client()) as connection:
        response = await connection.request(method,path,json=json,content=content)
        response.raise_for_status()
        return response.json()


def setup_status():
    # Safe public setup state only; never expose the private host configuration or log.
    for path in [Path('/run/pengucoach-maintenance/setup.json'),Path('/run/pengucoach-maintenance-setup.json')]:
        try:
            with path.open('r') as source:value=json.loads(source.read(4096))
            if isinstance(value,dict) and value.get('status') in {'running','ready','failed','deferred'}:
                return {k:value[k] for k in ['status','deployment','updated_at','code'] if k in value}
        except (OSError,ValueError):pass
    return None
