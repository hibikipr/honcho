#!/usr/bin/env python3
"""Read-only Honcho memory dashboard for honcho.townsville.cc/dashboard.

Serves index.html plus /api/summary (aggregated, cached for 60 s).
The Honcho admin token stays on this machine; the browser never sees it.
Stdlib only. Usage: server.py [port]  (default 8088)
"""
import base64, hashlib, hmac, json, os, re, sys, threading, time, urllib.request
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get('HONCHO_URL', 'http://localhost:8000')
WS = os.environ.get('HONCHO_WORKSPACE', 'claude_code')
PREFIX = '/dashboard'


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def token():
    """HONCHO_TOKEN if set, else a 1-hour admin JWT signed with AUTH_JWT_SECRET (read-only use)."""
    if os.environ.get('HONCHO_TOKEN'):
        return os.environ['HONCHO_TOKEN']
    secret = os.environ.get('AUTH_JWT_SECRET', '')
    if not secret:
        return ''
    head = _b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    body = _b64(json.dumps({'t': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                            'exp': int(time.time()) + 3600, 'ad': True}, separators=(',', ':')).encode())
    sig = _b64(hmac.new(secret.encode(), f'{head}.{body}'.encode(), hashlib.sha256).digest())
    return f'{head}.{body}.{sig}'
TTL = 60

TOPICS = {
    'api': r'\bapi\b', 'honcho': r'\bhoncho\b', 'townsville': r'townsville', 'docker': r'\bdocker\b',
    'auth': r'\bauth', 'token': r'\btokens?\b', 'ollama': r'\bollama\b', 'qwen': r'\bqwen',
    'deriver': r'\bderiver\b', 'nginx': r'\bnginx\b', 'embedding': r'\bembeddings?\b',
    'spoolbuddy': r'\bspoolbuddy\b', 'macbook': r'\bmacbook\b', 'tower': r'\btower\b',
    'hook': r'\bhooks?\b', 'mcp': r'\bmcp\b', 'dream': r'\bdream', 'raspberry': r'\braspberry\b',
    'vpn': r'\bvpn\b', 'jwt': r'\bjwt\b',
}
ENV_KEYS = {'EMBEDDING_MODEL_CONFIG__MODEL', 'EMBEDDING_VECTOR_DIMENSIONS', 'DERIVER_WORKERS', 'AUTH_USE_AUTH'}


def call(method, path, body=None, timeout=60):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def all_pages(path, body):
    items, page = [], 1
    while True:
        d = call('POST', f'{path}?page={page}&size=100', body)
        items += d.get('items', [])
        if page >= d.get('pages', 1):
            return items
        page += 1


def read_env():
    # Non-secret settings only, from the container environment (compose env_file).
    out, models = {}, set()
    for k, v in os.environ.items():
        if k in ENV_KEYS:
            out[k] = v.strip()
        elif k.endswith('__MODEL') and not k.startswith('EMBEDDING') and v.strip():
            models.add(v.strip())
    out['_models'] = sorted(models)
    return out


def build():
    w = f'/v3/workspaces/{WS}'
    try:
        healthy = urllib.request.urlopen(BASE + '/health', timeout=5).status == 200
    except Exception:
        healthy = False
    peers = [p['id'] for p in call('POST', w + '/peers/list', {}).get('items', [])]
    concl = {p: all_pages(w + '/conclusions/list', {'filters': {'observer_id': p}}) for p in peers}
    allc = [c for v in concl.values() for c in v]
    sess = all_pages(w + '/sessions/list', {})
    msgs = []
    for s in sorted(sess, key=lambda s: s['created_at']):
        try:
            total = call('POST', f"{w}/sessions/{s['id']}/messages/list?size=1", {}).get('total') or 0
        except Exception:
            total = 0
        msgs.append({'created': s['created_at'], 'messages': total})
    try:
        q = call('GET', w + '/queue/status')
    except Exception:
        q = {}
    cards = {}
    for p in peers:
        try:
            cards[p] = (call('GET', f'{w}/peers/{p}/card').get('peer_card') or [])
        except Exception:
            cards[p] = []

    days = {}
    for p, items in concl.items():
        for c in items:
            days.setdefault(c['created_at'][:10], Counter())[p] += 1
    levels = Counter(c['level'] for c in allc)
    text = [c['content'].lower() for c in allc]
    topics = sorted(((k, sum(1 for t in text if re.search(r, t))) for k, r in TOPICS.items()), key=lambda x: -x[1])[:12]
    reasoned = [{'who': p, 'level': c['level'], 'text': c['content'], 'at': c['created_at']}
                for p, items in concl.items() for c in items if c['level'] != 'explicit']
    reasoned.sort(key=lambda r: r['at'], reverse=True)
    user_peer = next((p for p in peers if p != 'claude'), peers[0] if peers else '')
    recent = sorted(concl.get(user_peer, []), key=lambda c: c['created_at'], reverse=True)[:8]
    env = read_env()
    return {
        'generated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'workspace': WS, 'userPeer': user_peer, 'healthy': healthy,
        'peers': {p: len(v) for p, v in concl.items()},
        'totals': {'conclusions': len(allc), 'sessions': len(sess), 'messages': sum(m['messages'] for m in msgs)},
        'levels': dict(levels),
        'days': [{'day': d, 'peers': dict(c)} for d, c in sorted(days.items())],
        'topics': [{'name': k, 'count': n} for k, n in topics],
        'reasoned': reasoned,
        'recent': [{'at': c['created_at'], 'text': c['content']} for c in recent],
        'card': cards.get(user_peer, []),
        'sessions': msgs,
        'queue': {k: q.get(k, 0) for k in ('total_work_units', 'completed_work_units', 'in_progress_work_units', 'pending_work_units')},
        'engine': {
            'models': env['_models'],
            'embedding': env.get('EMBEDDING_MODEL_CONFIG__MODEL', ''),
            'dims': env.get('EMBEDDING_VECTOR_DIMENSIONS', ''),
            'workers': env.get('DERIVER_WORKERS', ''),
            'auth': env.get('AUTH_USE_AUTH', '').lower() == 'true',
        },
    }


_cache = {'t': 0, 'data': None}
_lock = threading.Lock()


def summary():
    with _lock:
        if _cache['data'] is None or time.time() - _cache['t'] > TTL:
            _cache['data'] = build()
            _cache['t'] = time.time()
        return _cache['data']


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == PREFIX:
            return self.send(301, b'', 'text/plain', {'Location': PREFIX + '/'})
        if path.startswith(PREFIX + '/'):
            path = path[len(PREFIX):]
        if path in ('/', '/index.html'):
            return self.send(200, open(os.path.join(HERE, 'index.html'), 'rb').read(), 'text/html; charset=utf-8',
                             {'Content-Security-Policy': "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"})
        if path == '/api/summary':
            try:
                return self.send(200, json.dumps(summary()).encode(), 'application/json')
            except Exception as e:
                return self.send(502, json.dumps({'error': type(e).__name__}).encode(), 'application/json')
        if path == '/healthz':
            return self.send(200, b'ok', 'text/plain')
        self.send(404, b'not found', 'text/plain')


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8088
    ThreadingHTTPServer(('0.0.0.0', port), H).serve_forever()
