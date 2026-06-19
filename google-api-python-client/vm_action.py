"""
vm_action.py  — credentials を受け取って VM 上でコマンドを実行する

仕組み:
  - google.auth credentials で IAP WebSocket トンネルを確立
  - system ssh の ProxyCommand としてこのスクリプト自身を再実行
  - gcloud 不要・OS Config エージェント不要

必要条件:
  - openssh-client がインストールされていること
    Cloud Run の場合は Dockerfile に以下を追加:
      RUN apt-get install -y openssh-client

  - credentials に以下の権限:
    roles/iap.tunnelResourceAccessor  (VM 側プロジェクト)
    roles/compute.osLogin             (VM 側プロジェクト)
    roles/compute.viewer              (インスタンス解決に使う場合)

使い方:
    import google.auth
    from vm_action import action

    credentials, _ = google.auth.default()

    result = action(
        parameters={
            "instance": "test",
            "zone": "asia-northeast1-b",
            "project_id": "project_id",
            "command": "uptime",
        },
        credentials=credentials,
    )
    print(result)
"""

import base64
import os
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import traceback

import google.auth.transport.requests

# IAP TCP トンネル定数
_IAP_HOST = "tunnel.cloudproxy.app"
_IAP_PORT = 443
_IAP_PROTO = "relay.tunnel.cloudproxy.app"
_TAG_DATA = 0x00000004

# CA バンドル (企業プロキシ対応)
_CA = (
    os.environ.get("REQUESTS_CA_BUNDLE")
    or os.environ.get("SSL_CERT_FILE")
)


# ─── IAP WebSocket ────────────────────────────────────────────────────────────

class _PeekSocket:
    """HTTP ハンドシェイクで先読みした余剰バイトをソケット読み込みの先頭に戻すラッパー。"""

    def __init__(self, sock, buf: bytes = b""):
        self._sock = sock
        self._buf = buf

    def recv(self, n: int) -> bytes:
        if self._buf:
            chunk, self._buf = self._buf[:n], self._buf[n:]
            return chunk
        return self._sock.recv(n)

    def sendall(self, data: bytes) -> None:
        self._sock.sendall(data)

    def settimeout(self, t) -> None:
        self._sock.settimeout(t)


def _ws_connect(token: str, path: str) -> _PeekSocket:
    ctx = ssl.create_default_context(cafile=_CA) if _CA else ssl.create_default_context()
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
        raise RuntimeError(f"IAP WS ハンドシェイク失敗:\n{buf[:300].decode(errors='replace')}")
    sock.settimeout(None)  # データ転送中はブロッキングモードに切り替え (タイムアウト無効化)
    # ヘッダー末尾より後ろの余剰バイトを保持して返す
    extra = buf[buf.find(b"\r\n\r\n") + 4:]
    return _PeekSocket(sock, extra)


def _ws_recv(sock) -> bytes | None:
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
        if ln == 126:
            ln = struct.unpack(">H", read(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", read(8))[0]
        mask = read(4) if h[1] & 0x80 else b""
        payload = read(ln)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if op == 0x8:
            return None
        if op == 0x9:
            _ws_send(sock, payload, 0xA)
            continue
        if op == 0xA:
            continue
        if fin:
            return payload


def _ws_send(sock, data: bytes, op: int = 0x2):
    m = os.urandom(4)
    ln = len(data)
    hd = bytes([0x80 | op, 0x80 | (ln if ln < 126 else 126 if ln < 65536 else 127)])
    if ln >= 65536:
        hd += struct.pack(">Q", ln)
    elif ln >= 126:
        hd += struct.pack(">H", ln)
    sock.sendall(hd + m + bytes(b ^ m[i % 4] for i, b in enumerate(data)))


def _iap_recv(sock) -> bytes | None:
    while True:
        p = _ws_recv(sock)
        if p is None:
            return None
        if len(p) >= 8 and struct.unpack(">I", p[:4])[0] == _TAG_DATA:
            return p[8: 8 + struct.unpack(">I", p[4:8])[0]]


def _iap_send(sock, data: bytes):
    _ws_send(sock, struct.pack(">II", _TAG_DATA, len(data)) + data)


# ─── ProxyCommand モード (ssh から呼び出される) ───────────────────────────────

def _proxy_mode(instance: str, zone: str, proj_num: str, port: int, token_file: str):
    with open(token_file) as f:
        token = f.read().strip()
    path = (
        f"/v4/connect?project={proj_num}&zone={zone}"
        f"&instance={instance}&interface=nic0&port={port}"
    )
    ws = _ws_connect(token, path)
    stop = threading.Event()

    def to_iap():
        try:
            while not stop.is_set():
                d = os.read(sys.stdin.fileno(), 4096)
                if not d:
                    break
                _iap_send(ws, d)
        except Exception:
            traceback.print_exc(file=sys.stderr)
        finally:
            stop.set()

    def from_iap():
        try:
            while not stop.is_set():
                d = _iap_recv(ws)
                if d is None:
                    break
                sys.stdout.buffer.write(d)
                sys.stdout.buffer.flush()
        except Exception:
            traceback.print_exc(file=sys.stderr)
        finally:
            stop.set()

    threading.Thread(target=to_iap,   daemon=True).start()
    threading.Thread(target=from_iap, daemon=True).start()
    stop.wait()


# ─── プロジェクト番号取得 ─────────────────────────────────────────────────────

def _get_project_number(credentials, project_id: str) -> str:
    session = google.auth.transport.requests.AuthorizedSession(credentials)
    if _CA:
        session.verify = _CA
    resp = session.get(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}"
    )
    resp.raise_for_status()
    return resp.json()["projectNumber"]


# ─── メイン関数 ───────────────────────────────────────────────────────────────

def action(parameters: dict, credentials) -> str:
    """
    IAP SSH 経由で VM 上のコマンドを実行し、標準出力を返す。

    parameters キー:
        instance   : インスタンス名 (必須)
        zone       : ゾーン名 (必須)
        project_id : VM 側 GCP プロジェクトID (必須)
        command    : 実行するシェルコマンド (必須)
        port       : SSH ポート番号 (省略時: 22)
        user       : SSH ユーザー名 (省略時: OS Login のデフォルト)

    credentials:
        google.auth.credentials.Credentials
        VM 側プロジェクトの IAP・OS Login 権限を持つ認証情報
    """
    instance = parameters["instance"]
    zone = parameters["zone"]
    project_id = parameters["project_id"]
    command = parameters["command"]
    port = parameters.get("port", 22)
    user = parameters.get("user")

    # トークンを最新に更新
    credentials.refresh(google.auth.transport.requests.Request())
    token = credentials.token

    # プロジェクト番号取得 (IAP URL に必要)
    proj_num = _get_project_number(credentials, project_id)

    # アクセストークンを一時ファイルに保存 (ps で見えないように)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tok", delete=False, dir="/tmp") as f:
        f.write(token)
        tok_path = f.name
    os.chmod(tok_path, 0o600)

    try:
        script = os.path.abspath(__file__)
        proxy = (
            f"{sys.executable} {script} --proxy-mode"
            f" {instance} {zone} {proj_num} {port} {tok_path}"
        )
        target = f"{user}@{instance}" if user else instance
        ssh_cmd = [
            "ssh",
            "-vvv",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", f"ProxyCommand={proxy}",
            target,
            command,
        ]
        result = subprocess.run(ssh_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"SSH コマンド失敗 (exit {result.returncode}):\n{result.stderr}"
            )
        return result.stdout
    finally:
        try:
            os.unlink(tok_path)
        except OSError:
            pass


# ─── CLI (動作確認用) ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    # ProxyCommand として呼ばれた場合
    if len(sys.argv) > 1 and sys.argv[1] == "--proxy-mode":
        _, _, inst, zone, proj_num, port, tok = sys.argv
        _proxy_mode(inst, zone, proj_num, int(port), tok)
        sys.exit(0)

    import argparse
    import google.auth

    p = argparse.ArgumentParser(description="vm_action CLI (動作確認用)")
    p.add_argument("--instance",   required=True)
    p.add_argument("--zone",       required=True)
    p.add_argument("--project-id", required=True)
    p.add_argument("--command",    required=True)
    p.add_argument("--user",       default=None)
    p.add_argument("--port",       type=int, default=22)
    args = p.parse_args()

    creds, _ = google.auth.default()

    output = action(
        parameters={
            "instance":   args.instance,
            "zone":       args.zone,
            "project_id": args.project_id,
            "command":    args.command,
            "user":       args.user,
            "port":       args.port,
        },
        credentials=creds,
    )
    print(output, end="")
