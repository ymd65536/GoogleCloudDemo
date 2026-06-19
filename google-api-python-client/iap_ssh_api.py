"""
google-api-python-client + Python stdlib WebSocket で IAP TCP トンネルを実装し、
system ssh コマンドで GCE インスタンスに接続するスクリプト

- gcloud 不要 (system ssh を使用)
- 追加パッケージ不要 (stdlib: socket/ssl/struct/threading + 既存: google-auth/certifi)

仕組み:
  1. google-auth で ADC アクセストークンを取得
  2. Compute Engine API でインスタンス名・ゾーンを解決
  3. Cloud Resource Manager API でプロジェクト番号を取得
  4. このスクリプト自身を ssh の ProxyCommand として実行
  5. ProxyCommand モードで IAP WebSocket トンネルを確立し stdin/stdout を転送

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id

    # コマンドを実行して結果を表示
    python iap_ssh_api.py --instance-id osconfig-demo-c0f5ed --command "df -h"

    # 数値IDでも可
    python iap_ssh_api.py --instance-id {インスタンスID} --command "df -h"

    # インタラクティブシェルを開く
    python iap_ssh_api.py --instance-id osconfig-demo-c0f5ed

必要な権限:
    - roles/compute.viewer               (インスタンス情報取得)
    - roles/iap.tunnelResourceAccessor   (IAP TCP トンネル)
    - roles/compute.osLogin または SSH 公開鍵登録済み
"""

import argparse
import base64
import os
import struct
import subprocess
import sys
import tempfile
import threading
import certifi

# 環境変数が既に設定されている場合はそれを優先し、未設定時のみ certifi にフォールバック
_CA_BUNDLE = (
    os.environ.get("REQUESTS_CA_BUNDLE")
    or os.environ.get("SSL_CERT_FILE")
    or certifi.where()
)
os.environ["SSL_CERT_FILE"] = _CA_BUNDLE
os.environ["REQUESTS_CA_BUNDLE"] = _CA_BUNDLE

import google.auth
import google.auth.transport.requests
import google_auth_httplib2
import httplib2
from googleapiclient import discovery

# IAP TCP トンネルエンドポイント
_IAP_TUNNEL_HOST = "tunnel.cloudproxy.app"
_IAP_TUNNEL_PORT = 443
_IAP_SUBPROTOCOL = "relay.tunnel.cloudproxy.app"

# IAP relay プロトコルタグ
_TAG_CONNECT_SUCCESS_SID = 0x00000001
_TAG_DATA = 0x00000004


# ─── API ヘルパー ──────────────────────────────────────────────────────────────

def _build_compute_service(credentials):
    """httplib2 + CA バンドル指定で Compute Engine サービスを構築する。"""
    authorized_http = google_auth_httplib2.AuthorizedHttp(
        credentials, http=httplib2.Http(ca_certs=_CA_BUNDLE)
    )
    return discovery.build("compute", "v1", http=authorized_http)


def _get_project_id(project_id_arg: str | None = None) -> str:
    """プロジェクトID を解決する。引数 > 環境変数 > ADC の順。"""
    if project_id_arg:
        return project_id_arg
    pid = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if pid:
        return pid
    _, pid = google.auth.default()
    if not pid:
        raise ValueError(
            "プロジェクトIDが取得できません。"
            "GOOGLE_CLOUD_PROJECT を設定するか --project を指定してください。"
        )
    return pid


def _get_project_number(credentials, project_id: str) -> str:
    """Cloud Resource Manager API からプロジェクト番号を取得する。"""
    session = google.auth.transport.requests.AuthorizedSession(credentials)
    session.verify = _CA_BUNDLE
    resp = session.get(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}"
    )
    resp.raise_for_status()
    return resp.json()["projectNumber"]


def _resolve_instance(
    compute, project_id: str, instance_id_or_name: str, zone: str | None
) -> tuple[str, str]:
    """インスタンス名または数値ID からインスタンス名とゾーンを解決して返す。"""
    if instance_id_or_name.isdigit():
        numeric_id = instance_id_or_name
        print(f"  数値ID {numeric_id} からインスタンス情報を解決中...", file=sys.stderr)
        zones_to_search = (
            [zone] if zone
            else [z["name"] for z in compute.zones().list(project=project_id).execute().get("items", [])]
        )
        for z in zones_to_search:
            for inst in compute.instances().list(project=project_id, zone=z).execute().get("items", []):
                if str(inst.get("id", "")) == numeric_id:
                    print(f"  インスタンス名: {inst['name']}  ゾーン: {z}", file=sys.stderr)
                    return inst["name"], z
        raise ValueError(f"数値ID {numeric_id} のインスタンスが見つかりませんでした")

    if zone:
        inst = compute.instances().get(
            project=project_id, zone=zone, instance=instance_id_or_name
        ).execute()
        return inst["name"], zone
    else:
        print(f"  インスタンス '{instance_id_or_name}' のゾーンを検索中...", file=sys.stderr)
        for z in [zn["name"] for zn in compute.zones().list(project=project_id).execute().get("items", [])]:
            try:
                inst = compute.instances().get(
                    project=project_id, zone=z, instance=instance_id_or_name
                ).execute()
                print(f"  ゾーン: {z}", file=sys.stderr)
                return inst["name"], z
            except Exception:
                continue
        raise ValueError(f"インスタンス '{instance_id_or_name}' が見つかりませんでした")


# ─── WebSocket (Python stdlib のみ) ───────────────────────────────────────────

def _recv_exact(sock, n: int) -> bytes:
    """ソケットから正確に n バイト受信する。"""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("WebSocket 接続が切断されました")
        buf += chunk
    return buf


def _ws_handshake(sock, host: str, path: str, token: str):
    """HTTP → WebSocket アップグレードハンドシェイクを行う。"""
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Protocol: {_IAP_SUBPROTOCOL}\r\n"
        f"Authorization: Bearer {token}\r\n"
        f"\r\n"
    )
    sock.sendall(request.encode())

    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("WebSocket ハンドシェイク中に接続が切断されました")
        buf += chunk

    if b"101" not in buf:
        raise RuntimeError(
            f"WebSocket ハンドシェイク失敗:\n{buf.decode(errors='replace')[:500]}"
        )


def _ws_recv_frame(sock) -> bytes | None:
    """WebSocket フレームを受信してペイロードを返す (フラグメント対応)。"""
    fragments = []
    while True:
        h = _recv_exact(sock, 2)
        fin = bool(h[0] & 0x80)
        opcode = h[0] & 0x0F
        masked = bool(h[1] & 0x80)
        length = h[1] & 0x7F

        if length == 126:
            length = struct.unpack(">H", _recv_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", _recv_exact(sock, 8))[0]

        mask_key = _recv_exact(sock, 4) if masked else b""
        payload = _recv_exact(sock, length)
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

        if opcode == 0x8:   # Close
            return None
        if opcode == 0x9:   # Ping → Pong
            _ws_send_frame(sock, payload, opcode=0xA)
            continue
        if opcode == 0xA:   # Pong
            continue
        if opcode in (0x1, 0x2):    # Text / Binary (先頭フレーム)
            fragments = [payload]
        elif opcode == 0x0:         # Continuation
            fragments.append(payload)

        if fin:
            return b"".join(fragments)


def _ws_send_frame(sock, data: bytes, opcode: int = 0x2):
    """マスク付き WebSocket フレームを送信する。"""
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    length = len(data)
    if length < 126:
        header = bytes([0x80 | opcode, 0x80 | length]) + mask
    elif length < 65536:
        header = bytes([0x80 | opcode, 0xFE]) + struct.pack(">H", length) + mask
    else:
        header = bytes([0x80 | opcode, 0xFF]) + struct.pack(">Q", length) + mask
    sock.sendall(header + masked)


# ─── IAP relay プロトコル ──────────────────────────────────────────────────────

def _iap_recv_data(sock) -> bytes | None:
    """IAP relay フレームを受信し DATA タグのみ返す (制御フレームは読み捨て)。"""
    while True:
        payload = _ws_recv_frame(sock)
        if payload is None:
            return None
        if len(payload) < 8:
            continue
        tag = struct.unpack(">I", payload[:4])[0]
        length = struct.unpack(">I", payload[4:8])[0]
        if tag == _TAG_DATA:
            return payload[8: 8 + length]
        # CONNECT_SUCCESS_SID (0x1), ACK (0x5), STOP (0x7) などは無視


def _iap_send_data(sock, data: bytes):
    """IAP DATA フレームを送信する。"""
    frame = struct.pack(">II", _TAG_DATA, len(data)) + data
    _ws_send_frame(sock, frame)


# ─── Proxy mode (ssh の ProxyCommand として動作) ──────────────────────────────

def run_proxy_mode(
    instance: str, zone: str, project_number: str, port: int, token_file: str
):
    """
    ssh の ProxyCommand として呼び出されるモード。
    stdin ↔ IAP WebSocket トンネル ↔ stdout でデータを転送する。
    """
    import ssl
    import socket

    with open(token_file) as f:
        token = f.read().strip()

    path = (
        f"/v4/connect"
        f"?project={project_number}"
        f"&zone={zone}"
        f"&instance={instance}"
        f"&interface=nic0"
        f"&port={port}"
    )

    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=_CA_BUNDLE)
    raw = socket.create_connection((_IAP_TUNNEL_HOST, _IAP_TUNNEL_PORT), timeout=30)
    ws = ctx.wrap_socket(raw, server_hostname=_IAP_TUNNEL_HOST)
    _ws_handshake(ws, _IAP_TUNNEL_HOST, path, token)

    stop = threading.Event()

    def stdin_to_iap():
        try:
            while not stop.is_set():
                # os.read は利用可能なデータを即座に返す (最大 4096 バイト)
                data = os.read(sys.stdin.fileno(), 4096)
                if not data:
                    break
                _iap_send_data(ws, data)
        except Exception:
            pass
        finally:
            stop.set()

    def iap_to_stdout():
        try:
            while not stop.is_set():
                data = _iap_recv_data(ws)
                if data is None:
                    break
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
        except Exception:
            pass
        finally:
            stop.set()

    t1 = threading.Thread(target=stdin_to_iap, daemon=True)
    t2 = threading.Thread(target=iap_to_stdout, daemon=True)
    t1.start()
    t2.start()
    stop.wait()


# ─── Main SSH mode ────────────────────────────────────────────────────────────

def run_iap_ssh(
    instance_name: str,
    zone: str,
    project_number: str,
    token: str,
    command: str | None,
    user: str | None,
    port: int,
) -> int:
    """IAP トンネル経由で system ssh を実行する。"""
    script_path = os.path.abspath(__file__)
    target = f"{user}@{instance_name}" if user else instance_name

    # アクセストークンを一時ファイルに書き込む (コマンドライン引数に直接渡すと ps で見える)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".iaptoken", delete=False, prefix="iap_", dir="/tmp"
    ) as f:
        f.write(token)
        token_file = f.name
    os.chmod(token_file, 0o600)

    try:
        proxy_cmd = (
            f"python3 {script_path} --proxy-mode"
            f" {instance_name} {zone} {project_number} {port} {token_file}"
        )

        ssh_cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", f"ProxyCommand={proxy_cmd}",
            target,
        ]
        if command:
            ssh_cmd.append(command)

        print("  接続中 (IAP WebSocket Tunnel → system ssh)...", file=sys.stderr)
        print(f"  対象: {target}", file=sys.stderr)
        print(file=sys.stderr)

        if command:
            result = subprocess.run(ssh_cmd, capture_output=True, text=True)
            if result.stdout:
                print("--- 実行結果 ---")
                print(result.stdout.rstrip())
                print("----------------")
            if result.returncode != 0 and result.stderr:
                # ssh の警告行を除いてエラーのみ表示
                for line in result.stderr.splitlines():
                    if "WARNING:" not in line and "Warning:" not in line:
                        print(line, file=sys.stderr)
            return result.returncode
        else:
            return subprocess.run(ssh_cmd).returncode
    finally:
        try:
            os.unlink(token_file)
        except OSError:
            pass


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    # --proxy-mode は argparse の前にチェック (ProxyCommand から呼ばれるため)
    # 形式: script.py --proxy-mode <instance> <zone> <project_number> <port> <token_file>
    if len(sys.argv) > 1 and sys.argv[1] == "--proxy-mode":
        if len(sys.argv) != 7:
            print("Usage (proxy): script --proxy-mode instance zone project_number port token_file",
                  file=sys.stderr)
            sys.exit(1)
        _, _, instance, zone, project_number, port_str, token_file = sys.argv
        run_proxy_mode(instance, zone, project_number, int(port_str), token_file)
        return

    parser = argparse.ArgumentParser(
        description=(
            "IAP TCP トンネル (Python stdlib WebSocket) 経由で GCE に SSH 接続する。"
            " gcloud 不要・追加パッケージ不要。"
        )
    )
    parser.add_argument("--instance-id", required=True,
                        help="インスタンス名または数値ID")
    parser.add_argument("--zone", default=os.environ.get("GOOGLE_CLOUD_ZONE"),
                        help="ゾーン名 (省略時は自動検索、環境変数 GOOGLE_CLOUD_ZONE も利用可)")
    parser.add_argument("--project", default=None,
                        help="GCP プロジェクトID (省略時は GOOGLE_CLOUD_PROJECT または ADC)")
    parser.add_argument("--command", default=None,
                        help="リモートで実行するコマンド (省略時はインタラクティブシェル)")
    parser.add_argument("--user", default=None,
                        help="SSH ユーザー名 (省略時は OS Login のデフォルト)")
    parser.add_argument("--port", type=int, default=22,
                        help="SSH ポート番号 (デフォルト: 22)")
    args = parser.parse_args()

    # プロジェクトID 解決
    try:
        project_id = _get_project_id(args.project)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    # ADC 認証・トークン取得
    credentials, _ = google.auth.default()
    credentials.refresh(google.auth.transport.requests.Request())
    token = credentials.token

    # インスタンス解決
    compute = _build_compute_service(credentials)
    try:
        instance_name, zone = _resolve_instance(
            compute, project_id, args.instance_id, args.zone
        )
    except Exception as e:
        print(f"エラー: インスタンスの解決に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    # プロジェクト番号取得 (IAP トンネル URL に必要)
    try:
        project_number = _get_project_number(credentials, project_id)
    except Exception as e:
        print(f"エラー: プロジェクト番号の取得に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    print("[IAP SSH API] 接続情報", file=sys.stderr)
    print(f"  インスタンス   : {instance_name}", file=sys.stderr)
    print(f"  ゾーン         : {zone}", file=sys.stderr)
    print(f"  プロジェクト   : {project_id} (番号: {project_number})", file=sys.stderr)
    print(f"  ポート         : {args.port}", file=sys.stderr)
    if args.command:
        print(f"  コマンド       : {args.command}", file=sys.stderr)
    else:
        print("  モード         : インタラクティブシェル", file=sys.stderr)

    exit_code = run_iap_ssh(
        instance_name=instance_name,
        zone=zone,
        project_number=project_number,
        token=token,
        command=args.command,
        user=args.user,
        port=args.port,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
