"""
IAP TCP Tunnel + system ssh で GCE に接続する最小実装

- google-cloud-compute (compute_v1) でインスタンス解決
- google.auth.transport.requests で認証・プロジェクト番号取得
- Python stdlib (socket/ssl/struct/threading) で WebSocket トンネル
- system ssh の ProxyCommand としてこのスクリプト自身を再実行

追加インストール不要 (google-cloud-compute / google-auth / certifi は既存)

使い方:
    python iap_ssh_min.py --instance-id osconfig-demo-c0f5ed --command "df -h"
    python iap_ssh_min.py --instance-id {インスタンスID}
"""

import argparse
import base64
import os
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import certifi
import google.auth
import google.auth.transport.requests
from google.cloud import compute_v1

# ─── CA バンドル ─────────────────────────────────────────────────────────────
_CA = (
    os.environ.get("REQUESTS_CA_BUNDLE")
    or os.environ.get("SSL_CERT_FILE")
    or certifi.where()
)
os.environ.setdefault("SSL_CERT_FILE", _CA)
os.environ.setdefault("REQUESTS_CA_BUNDLE", _CA)

# ─── IAP 定数 ────────────────────────────────────────────────────────────────
_IAP_HOST  = "tunnel.cloudproxy.app"
_IAP_PORT  = 443
_IAP_PROTO = "relay.tunnel.cloudproxy.app"
_TAG_DATA  = 0x00000004


# ─── 認証・API ────────────────────────────────────────────────────────────────

def _get_credentials():
    creds, _ = google.auth.default()
    creds.refresh(google.auth.transport.requests.Request())
    return creds


def _get_project_id(arg: str | None) -> str:
    if arg:
        return arg
    pid = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if pid:
        return pid
    _, pid = google.auth.default()
    if not pid:
        raise ValueError("GOOGLE_CLOUD_PROJECT が未設定です。--project で指定してください。")
    return pid


def _get_project_number(creds, project_id: str) -> str:
    session = google.auth.transport.requests.AuthorizedSession(creds)
    session.verify = _CA
    resp = session.get(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}"
    )
    resp.raise_for_status()
    return resp.json()["projectNumber"]


def _resolve_instance(project_id: str, instance_id_or_name: str, zone: str | None) -> tuple[str, str]:
    """インスタンス名または数値IDからインスタンス名とゾーンを返す。"""
    instances_client = compute_v1.InstancesClient(transport="rest")
    zones_client = compute_v1.ZonesClient(transport="rest")

    if instance_id_or_name.isdigit():
        print(f"  数値ID {instance_id_or_name} を解決中...", file=sys.stderr)
        zone_list = [zone] if zone else [
            z.name for z in zones_client.list(project=project_id)
        ]
        for z in zone_list:
            for inst in instances_client.list(project=project_id, zone=z):
                if str(inst.id) == instance_id_or_name:
                    print(f"  → {inst.name} / {z}", file=sys.stderr)
                    return inst.name, z
        raise ValueError(f"数値ID {instance_id_or_name} のインスタンスが見つかりません")

    if zone:
        return instance_id_or_name, zone

    print(f"  '{instance_id_or_name}' のゾーンを検索中...", file=sys.stderr)
    for z in [z.name for z in zones_client.list(project=project_id)]:
        try:
            instances_client.get(project=project_id, zone=z, instance=instance_id_or_name)
            print(f"  → ゾーン: {z}", file=sys.stderr)
            return instance_id_or_name, z
        except Exception:
            continue
    raise ValueError(f"インスタンス '{instance_id_or_name}' が見つかりません")


# ─── WebSocket (stdlib) ───────────────────────────────────────────────────────

def _ws_connect(token: str, path: str) -> ssl.SSLSocket:
    """IAP WebSocket トンネルに接続し ssl.SSLSocket を返す。"""
    ctx = ssl.create_default_context(cafile=_CA)
    sock = ctx.wrap_socket(
        socket.create_connection((_IAP_HOST, _IAP_PORT), timeout=30),
        server_hostname=_IAP_HOST,
    )
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {_IAP_HOST}\r\n"
        f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Protocol: {_IAP_PROTO}\r\n"
        f"Authorization: Bearer {token}\r\n\r\n"
    ).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += sock.recv(4096)
    if b"101" not in buf:
        raise RuntimeError(f"WS ハンドシェイク失敗:\n{buf[:300].decode(errors='replace')}")
    return sock


def _ws_recv(sock) -> bytes | None:
    """WebSocket フレームを受信してペイロードを返す。"""
    def read(n):
        b = b""
        while len(b) < n:
            c = sock.recv(n - len(b))
            if not c:
                raise EOFError
            b += c
        return b

    while True:
        h = read(2)
        fin, op = bool(h[0] & 0x80), h[0] & 0x0F
        ln = h[1] & 0x7F
        if ln == 126: ln = struct.unpack(">H", read(2))[0]
        elif ln == 127: ln = struct.unpack(">Q", read(8))[0]
        mask = read(4) if h[1] & 0x80 else b""
        payload = read(ln)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if op == 0x8: return None       # Close
        if op == 0x9: _ws_send(sock, payload, 0xA); continue  # Ping→Pong
        if op == 0xA: continue          # Pong
        if fin: return payload


def _ws_send(sock, data: bytes, op: int = 0x2):
    """マスク付き WebSocket フレームを送信する。"""
    m = os.urandom(4)
    ln = len(data)
    hd = bytes([0x80 | op, 0x80 | (ln if ln < 126 else 126 if ln < 65536 else 127)])
    if ln >= 65536: hd += struct.pack(">Q", ln)
    elif ln >= 126: hd += struct.pack(">H", ln)
    sock.sendall(hd + m + bytes(b ^ m[i % 4] for i, b in enumerate(data)))


def _iap_recv(sock) -> bytes | None:
    while True:
        p = _ws_recv(sock)
        if p is None: return None
        if len(p) >= 8 and struct.unpack(">I", p[:4])[0] == _TAG_DATA:
            return p[8: 8 + struct.unpack(">I", p[4:8])[0]]


def _iap_send(sock, data: bytes):
    _ws_send(sock, struct.pack(">II", _TAG_DATA, len(data)) + data)


# ─── ProxyCommand モード ──────────────────────────────────────────────────────

def _proxy_mode(instance: str, zone: str, proj_num: str, port: int, token_file: str):
    with open(token_file) as f:
        token = f.read().strip()
    path = f"/v4/connect?project={proj_num}&zone={zone}&instance={instance}&interface=nic0&port={port}"
    ws = _ws_connect(token, path)
    stop = threading.Event()

    def to_iap():
        try:
            while not stop.is_set():
                d = os.read(sys.stdin.fileno(), 4096)
                if not d: break
                _iap_send(ws, d)
        finally: stop.set()

    def from_iap():
        try:
            while not stop.is_set():
                d = _iap_recv(ws)
                if d is None: break
                sys.stdout.buffer.write(d); sys.stdout.buffer.flush()
        finally: stop.set()

    threading.Thread(target=to_iap,   daemon=True).start()
    threading.Thread(target=from_iap, daemon=True).start()
    stop.wait()


# ─── メイン ──────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--proxy-mode":
        _, _, inst, zone, proj_num, port, tok = sys.argv
        _proxy_mode(inst, zone, proj_num, int(port), tok)
        return

    p = argparse.ArgumentParser(description="IAP WebSocket + ssh (gcloud 不要)")
    p.add_argument("--instance-id", required=True)
    p.add_argument("--zone", default=os.environ.get("GOOGLE_CLOUD_ZONE"))
    p.add_argument("--project", default=None)
    p.add_argument("--command", default=None)
    p.add_argument("--user", default=None)
    p.add_argument("--port", type=int, default=22)
    args = p.parse_args()

    project_id = _get_project_id(args.project)
    creds = _get_credentials()
    inst, zone = _resolve_instance(project_id, args.instance_id, args.zone)
    proj_num = _get_project_number(creds, project_id)

    print(f"  インスタンス: {inst} / {zone} / {project_id}", file=sys.stderr)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".tok", delete=False, dir="/tmp") as f:
        f.write(creds.token); tok_path = f.name
    os.chmod(tok_path, 0o600)

    try:
        script = os.path.abspath(__file__)
        proxy  = f"python3 {script} --proxy-mode {inst} {zone} {proj_num} {args.port} {tok_path}"
        target = f"{args.user}@{inst}" if args.user else inst
        ssh    = ["ssh", "-o", "StrictHostKeyChecking=no",
                        "-o", "UserKnownHostsFile=/dev/null",
                        "-o", f"ProxyCommand={proxy}", target]
        if args.command:
            result = subprocess.run(ssh + [args.command], capture_output=True, text=True)
            if result.stdout:
                print("--- 実行結果 ---")
                print(result.stdout.rstrip())
                print("----------------")
            if result.returncode != 0 and result.stderr:
                print(result.stderr.rstrip(), file=sys.stderr)
            sys.exit(result.returncode)
        else:
            sys.exit(subprocess.run(ssh).returncode)
    finally:
        try: os.unlink(tok_path)
        except OSError: pass


if __name__ == "__main__":
    main()
