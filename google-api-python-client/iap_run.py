"""
gcloud (ローカル) で IAP SSH トンネルを確立し、リモート VM でコマンドを実行する

前提条件:
  - ローカルに gcloud がインストール済み
  - gcloud auth application-default login 済み
  - roles/iap.tunnelResourceAccessor 権限あり
  - roles/compute.osLogin または SSH 公開鍵登録済み

使い方:
    python iap_run.py --instance-id mspdev-test --command "df -h"
    .venv/bin/python google-api-python-client/iap_run.py --instance-id {} --command "df -h"
    python iap_run.py --instance-id mspdev-test   # インタラクティブシェル
"""

import argparse
import os
import subprocess
import sys


def _gcloud(*args, check=True) -> subprocess.CompletedProcess:
    cmd = ["gcloud", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _get_project(arg: str | None) -> str:
    if arg:
        return arg
    pid = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if pid:
        return pid
    r = _gcloud("config", "get-value", "project")
    pid = r.stdout.strip()
    if not pid or pid == "(unset)":
        raise ValueError(
            "プロジェクトIDが取得できません。"
            "GOOGLE_CLOUD_PROJECT を設定するか --project を指定してください。"
        )
    return pid


def _resolve_instance(name_or_id: str, project: str, zone: str | None) -> tuple[str, str]:
    """インスタンス名または数値IDからインスタンス名とゾーンを返す。"""
    if not name_or_id.isdigit():
        # 名前指定: ゾーンが未指定なら gcloud で検索
        if zone:
            return name_or_id, zone
        print(f"  '{name_or_id}' のゾーンを検索中...", file=sys.stderr)
        r = _gcloud(
            "compute", "instances", "list",
            f"--filter=name={name_or_id}",
            "--format=value(name,zone)",
            f"--project={project}",
        )
        line = r.stdout.strip()
        if not line:
            raise ValueError(f"インスタンス '{name_or_id}' が見つかりません")
        name, z = line.split("\t")
        print(f"  → ゾーン: {z}", file=sys.stderr)
        return name, z

    # 数値ID指定
    print(f"  数値ID {name_or_id} を解決中...", file=sys.stderr)
    filter_arg = f"--filter=id={name_or_id}"
    r = _gcloud(
        "compute", "instances", "list",
        filter_arg,
        "--format=value(name,zone)",
        f"--project={project}",
        *([f"--zones={zone}"] if zone else []),
    )
    line = r.stdout.strip()
    if not line:
        raise ValueError(f"数値ID {name_or_id} のインスタンスが見つかりません")
    name, z = line.split("\t")
    print(f"  → {name} / {z}", file=sys.stderr)
    return name, z


def iap_run(
    instance: str,
    zone: str,
    project: str,
    command: str | None,
    user: str | None,
    port: int,
) -> int:
    target = f"{user}@{instance}" if user else instance
    cmd = [
        "gcloud", "compute", "ssh", target,
        f"--zone={zone}",
        f"--project={project}",
        "--tunnel-through-iap",
        f"--ssh-flag=-p {port}",
        "--ssh-flag=-o StrictHostKeyChecking=no",
        "--ssh-flag=-o UserKnownHostsFile=/dev/null",
    ]
    if command:
        cmd += ["--command", command]

    print(f"  接続先: {target}  ゾーン: {zone}", file=sys.stderr)
    if command:
        print(f"  コマンド: {command}", file=sys.stderr)
    else:
        print("  モード: インタラクティブシェル", file=sys.stderr)
    print(file=sys.stderr)

    if command:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            print("--- 実行結果 ---")
            print(result.stdout.rstrip())
            print("----------------")
        if result.returncode != 0 and result.stderr:
            # gcloud/ssh の警告行を除いてエラーのみ表示
            for line in result.stderr.splitlines():
                if "WARNING" not in line and "Warning" not in line:
                    print(line, file=sys.stderr)
        return result.returncode
    else:
        return subprocess.run(cmd).returncode


def main():
    p = argparse.ArgumentParser(description="IAP SSH 経由で VM にコマンドを実行 (gcloud 使用)")
    p.add_argument("--instance-id", required=True, help="インスタンス名または数値ID")
    p.add_argument("--command", default=None, help="実行するコマンド (省略時はインタラクティブシェル)")
    p.add_argument("--zone",    default=os.environ.get("GOOGLE_CLOUD_ZONE"),
                   help="ゾーン名 (省略時は自動検索、GOOGLE_CLOUD_ZONE も利用可)")
    p.add_argument("--project", default=None,
                   help="GCP プロジェクトID (省略時は GOOGLE_CLOUD_PROJECT)")
    p.add_argument("--user",    default=None, help="SSH ユーザー名")
    p.add_argument("--port",    type=int, default=22, help="SSH ポート番号 (デフォルト: 22)")
    args = p.parse_args()

    try:
        project = _get_project(args.project)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  プロジェクト: {project}", file=sys.stderr)

    try:
        inst, zone = _resolve_instance(args.instance_id, project, args.zone)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    sys.exit(iap_run(inst, zone, project, args.command, args.user, args.port))


if __name__ == "__main__":
    main()
