"""
google-api-python-client でインスタンス情報を取得し、
IAP (Identity-Aware Proxy) 経由で SSH 接続するスクリプト

- Compute Engine API でインスタンス名/ゾーンを解決
- gcloud compute ssh --tunnel-through-iap をサブプロセスで実行
- コマンド指定時はリモートで実行して結果を返す
- コマンド未指定時はインタラクティブシェルを開く

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id

    # インタラクティブシェルを開く (インスタンス名)
    python iap_ssh.py --instance-id {インスタンスID}

    # インタラクティブシェルを開く (数値ID)
    python iap_ssh.py --instance-id {インスタンスID}

    # リモートでコマンドを実行して結果を表示
    python iap_ssh.py --instance-id {インスタンスID} --command "df -h"

    # SSH ユーザー・ポートを指定
    python iap_ssh.py --instance-id {インスタンスID} --user {user_id} --port 22

必要な権限:
    - roles/compute.viewer          (インスタンス情報取得)
    - roles/iap.tunnelResourceAccessor (IAP トンネル)
    - roles/compute.osLogin または メタデータに SSH 公開鍵
"""

import argparse
import os
import subprocess
import sys
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
import google_auth_httplib2
import httplib2
from googleapiclient import discovery


def _build_compute_service(credentials):
    """SSL 証明書を指定した httplib2 経由で Compute Engine サービスを構築する。"""
    authorized_http = google_auth_httplib2.AuthorizedHttp(
        credentials, http=httplib2.Http(ca_certs=_CA_BUNDLE)
    )
    return discovery.build("compute", "v1", http=authorized_http)


def _get_project_id(project_id_arg: str | None = None) -> str:
    """プロジェクトIDを解決する。引数 > 環境変数 > ADC の順で取得。"""
    if project_id_arg:
        return project_id_arg
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project_id:
        return project_id
    _, project_id = google.auth.default()
    if not project_id:
        raise ValueError(
            "プロジェクトIDが取得できません。"
            "GOOGLE_CLOUD_PROJECT を設定するか --project を指定してください。"
        )
    return project_id


def _resolve_instance(
    compute, project_id: str, instance_id_or_name: str, zone: str | None
) -> tuple[str, str]:
    """インスタンスIDまたは名前からインスタンス名とゾーンを解決して返す。

    Returns:
        (instance_name, zone)
    """
    # 数値IDの場合: 全ゾーン (または指定ゾーン) を検索
    if instance_id_or_name.isdigit():
        numeric_id = instance_id_or_name
        print(f"  数値ID {numeric_id} からインスタンス情報を解決中...")

        if zone:
            zones_to_search = [zone]
        else:
            # ゾーン一覧を取得して全ゾーン検索
            zones_resp = compute.zones().list(project=project_id).execute()
            zones_to_search = [z["name"] for z in zones_resp.get("items", [])]

        for z in zones_to_search:
            result = compute.instances().list(project=project_id, zone=z).execute()
            for inst in result.get("items", []):
                if str(inst.get("id", "")) == numeric_id:
                    print(f"  インスタンス名: {inst['name']}  ゾーン: {z}")
                    return inst["name"], z

        raise ValueError(
            f"数値ID {numeric_id} のインスタンスが見つかりませんでした"
            + (f" (ゾーン: {zone})" if zone else "")
        )

    # インスタンス名の場合
    if zone:
        # ゾーン指定あり: 直接取得
        inst = compute.instances().get(
            project=project_id, zone=zone, instance=instance_id_or_name
        ).execute()
        return inst["name"], zone
    else:
        # ゾーン指定なし: 全ゾーン検索
        print(f"  インスタンス '{instance_id_or_name}' のゾーンを検索中...")
        zones_resp = compute.zones().list(project=project_id).execute()
        for z in [zn["name"] for zn in zones_resp.get("items", [])]:
            try:
                inst = compute.instances().get(
                    project=project_id, zone=z, instance=instance_id_or_name
                ).execute()
                print(f"  ゾーン: {z}")
                return inst["name"], z
            except Exception:
                continue
        raise ValueError(
            f"インスタンス '{instance_id_or_name}' が見つかりませんでした"
        )


def iap_ssh(
    instance_name: str,
    zone: str,
    project_id: str,
    command: str | None = None,
    user: str | None = None,
    port: int = 22,
    ssh_flag: list[str] | None = None,
) -> int:
    """IAP 経由で SSH 接続する。

    Args:
        instance_name: 接続先インスタンス名
        zone: インスタンスのゾーン
        project_id: GCP プロジェクトID
        command: リモートで実行するコマンド (None でインタラクティブ)
        user: SSH ユーザー名 (None で gcloud のデフォルト)
        port: SSH ポート番号
        ssh_flag: 追加の SSH フラグ (例: ["-o", "StrictHostKeyChecking=no"])

    Returns:
        終了コード
    """
    cmd = [
        "gcloud", "compute", "ssh", instance_name,
        f"--zone={zone}",
        f"--project={project_id}",
        "--tunnel-through-iap",
        f"--ssh-flag=-p {port}",
    ]

    if user:
        cmd[2] = f"{user}@{instance_name}"

    if ssh_flag:
        for flag in ssh_flag:
            cmd.append(f"--ssh-flag={flag}")

    if command:
        cmd += ["--command", command]

    print()
    print("[IAP SSH] 接続情報")
    print(f"  インスタンス : {instance_name}")
    print(f"  ゾーン       : {zone}")
    print(f"  プロジェクト : {project_id}")
    print(f"  ポート       : {port}")
    if command:
        print(f"  コマンド     : {command}")
    else:
        print("  モード       : インタラクティブシェル")
    print()
    print(f"  実行: {' '.join(cmd)}")
    print()

    # コマンド実行時は結果をキャプチャして表示、インタラクティブ時はそのまま引き継ぐ
    if command:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            print("--- 実行結果 ---")
            print(result.stdout.rstrip())
            print("----------------")
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        return result.returncode
    else:
        # インタラクティブ: stdin/stdout/stderr をそのまま引き継ぐ
        result = subprocess.run(cmd)
        return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="IAP 経由で GCE インスタンスに SSH 接続する"
    )
    parser.add_argument(
        "--instance-id",
        required=True,
        help="インスタンス名または数値ID (例: my-instance, {インスタンスID})",
    )
    parser.add_argument(
        "--zone",
        default=os.environ.get("GOOGLE_CLOUD_ZONE"),
        help="ゾーン名 (省略時は自動検索、環境変数 GOOGLE_CLOUD_ZONE も利用可)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="GCP プロジェクトID (省略時は環境変数 GOOGLE_CLOUD_PROJECT または ADC)",
    )
    parser.add_argument(
        "--command",
        default=None,
        help="リモートで実行するコマンド (省略時はインタラクティブシェル)",
    )
    parser.add_argument(
        "--user",
        default=None,
        help="SSH ユーザー名 (省略時は gcloud のデフォルト)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=22,
        help="SSH ポート番号 (デフォルト: 22)",
    )
    parser.add_argument(
        "--ssh-flag",
        action="append",
        default=[],
        metavar="FLAG",
        help="追加の SSH フラグ (複数指定可, 例: --ssh-flag='-o StrictHostKeyChecking=no')",
    )
    args = parser.parse_args()

    # プロジェクトID を解決
    try:
        project_id = _get_project_id(args.project)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    # Compute Engine API でインスタンス情報を解決
    credentials, _ = google.auth.default()
    compute = _build_compute_service(credentials)

    try:
        instance_name, zone = _resolve_instance(
            compute, project_id, args.instance_id, args.zone
        )
    except Exception as e:
        print(f"エラー: インスタンスの解決に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    exit_code = iap_ssh(
        instance_name=instance_name,
        zone=zone,
        project_id=project_id,
        command=args.command,
        user=args.user,
        port=args.port,
        ssh_flag=args.ssh_flag,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
