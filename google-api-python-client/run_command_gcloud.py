"""
gcloud コマンドをサブプロセスで実行して OS Config 経由で GCE にコマンドを送信するスクリプト

- gcloud compute os-config os-policy-assignments で OSPolicyAssignment を作成
- 実行結果 (osPolicyAssignmentReports) を取得して表示
- 完了後に Assignment を自動削除 (ジョブを残さない)
- Cloud Logging への書き込みなし
- デフォルトコマンド: df -h (ディスク使用量)
- インスタンス名/数値ID またはラベル指定が必須

使い方:
    # インスタンス名 or 数値ID で指定
    python run_command_gcloud.py --instance-id {インスタンスID}
    python run_command_gcloud.py --instance-id {インスタンスID}

    # ラベルで指定 (KEY=VALUE 形式)
    python run_command_gcloud.py --label managed-by=osconfig

    # コマンドを指定
    python run_command_gcloud.py --instance-id {インスタンスID} --command "free -h"

必要な権限:
    - roles/osconfig.osPolicyAssignmentAdmin
    - roles/compute.instanceAdmin.v1 (インスタンスID 指定時のラベル操作)
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid

# デフォルトコマンド: ディスク使用量
_DEFAULT_COMMAND = "df -h"

# ポーリング間隔 (秒)
_POLL_INTERVAL = 5

# レポート取得の最大待機時間 (秒)
_REPORT_WAIT_SECONDS = 60

# インスタンスID 指定時に付与する一時ラベルのキー
_TEMP_LABEL_KEY = "osconfig-tmp-target"


def _run_gcloud(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """gcloud コマンドをサブプロセスで実行し結果を返す。"""
    cmd = ["gcloud"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"gcloud コマンドが失敗しました\n"
            f"  コマンド: {' '.join(cmd)}\n"
            f"  stderr  : {result.stderr.strip()}"
        )
    return result


def _get_project_id() -> str:
    """環境変数または gcloud config からプロジェクトIDを取得する。"""
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project_id:
        return project_id
    result = _run_gcloud(["config", "get-value", "project"])
    project_id = result.stdout.strip()
    if not project_id or project_id == "(unset)":
        raise ValueError(
            "プロジェクトIDが取得できません。"
            "GOOGLE_CLOUD_PROJECT を設定するか gcloud config set project を実行してください。"
        )
    return project_id


def _resolve_instance_name(instance_id_or_name: str, project_id: str, zone: str) -> str:
    """数値IDまたはインスタンス名を受け取り、インスタンス名を返す。"""
    if not instance_id_or_name.isdigit():
        return instance_id_or_name  # すでにインスタンス名

    numeric_id = instance_id_or_name
    print(f"  数値ID {numeric_id} からインスタンス名を解決中...")
    result = _run_gcloud([
        "compute", "instances", "list",
        f"--filter=id={numeric_id}",
        "--format=value(name)",
        f"--zones={zone}",
        f"--project={project_id}",
    ])
    name = result.stdout.strip()
    if not name:
        raise ValueError(
            f"ゾーン {zone} に数値ID {numeric_id} のインスタンスが見つかりませんでした"
        )
    print(f"  インスタンス名: {name}")
    return name


def _add_temp_label(instance_name: str, label_value: str, project_id: str, zone: str) -> None:
    """インスタンスに一時ラベルを付与する。"""
    _run_gcloud([
        "compute", "instances", "add-labels", instance_name,
        f"--labels={_TEMP_LABEL_KEY}={label_value}",
        f"--zone={zone}",
        f"--project={project_id}",
    ])
    print(f"  一時ラベルを付与しました: {_TEMP_LABEL_KEY}={label_value}")


def _remove_temp_label(instance_name: str, project_id: str, zone: str) -> None:
    """インスタンスから一時ラベルを削除する。"""
    try:
        _run_gcloud([
            "compute", "instances", "remove-labels", instance_name,
            f"--labels={_TEMP_LABEL_KEY}",
            f"--zone={zone}",
            f"--project={project_id}",
        ])
        print(f"  一時ラベルを削除しました: {_TEMP_LABEL_KEY}")
    except Exception as e:
        print(f"  警告: 一時ラベルの削除に失敗しました: {e}", file=sys.stderr)


def _build_policy_yaml(command: str, label_key: str, label_value: str) -> str:
    """OS Policy Assignment の YAML 文字列を組み立てる。
    コマンドは YAML リテラルブロック (|) に 12 スペースインデントで埋め込む。
    """
    indented_cmd = "\n".join(f"            {line}" for line in command.splitlines())
    return f"""osPolicies:
- id: exec-command-policy
  mode: ENFORCEMENT
  resourceGroups:
  - resources:
    - id: run-command
      exec:
        validate:
          interpreter: SHELL
          script: exit 101
        enforce:
          interpreter: SHELL
          script: |
{indented_cmd}
            exit 100
instanceFilter:
  inclusionLabels:
  - labels:
      {label_key}: {label_value}
rollout:
  disruptionBudget:
    percent: 100
  minWaitDuration: 0s
"""


def _create_assignment(
    assignment_id: str, zone: str, yaml_content: str, project_id: str
) -> None:
    """一時 YAML ファイルを作成して gcloud で OSPolicyAssignment を作成する。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(yaml_content)
        yaml_path = f.name

    try:
        _run_gcloud([
            "compute", "os-config", "os-policy-assignments", "create", assignment_id,
            f"--location={zone}",
            f"--file={yaml_path}",
            f"--project={project_id}",
        ])
    finally:
        os.unlink(yaml_path)


def _fetch_reports(assignment_id: str, zone: str, project_id: str) -> list:
    """osPolicyAssignmentReports からレポートを取得する (最大 _REPORT_WAIT_SECONDS 秒待機)。"""
    print("  実行結果を取得中", end="", flush=True)
    for _ in range(_REPORT_WAIT_SECONDS // _POLL_INTERVAL):
        time.sleep(_POLL_INTERVAL)
        print(".", end="", flush=True)
        try:
            result = _run_gcloud([
                "compute", "os-config", "os-policy-assignments", "reports", "list",
                f"--location={zone}",
                f"--os-policy-assignment={assignment_id}",
                f"--project={project_id}",
                "--format=json",
            ], check=False)
            if result.returncode == 0 and result.stdout.strip():
                reports = json.loads(result.stdout)
                if reports:
                    print()
                    return reports
        except Exception:
            pass
    print()
    return []


def _delete_assignment(assignment_id: str, zone: str, project_id: str) -> None:
    """Assignment を削除する (ジョブを残さない)。"""
    try:
        _run_gcloud([
            "compute", "os-config", "os-policy-assignments", "delete", assignment_id,
            f"--location={zone}",
            f"--project={project_id}",
            "--quiet",
        ])
        print(f"  Assignment を削除しました: {assignment_id}")
    except Exception as e:
        print(f"  警告: Assignment の削除に失敗しました: {e}", file=sys.stderr)


def _print_reports(reports: list) -> None:
    """レポートの実行結果 (enforcementOutput) を表示する。"""
    print()
    print("=" * 60)
    print("実行結果")
    print("=" * 60)
    for report in reports:
        instance = report.get("instance", "").split("/")[-1]
        update_time = report.get("updateTime", "")
        print(f"インスタンス : {instance}")
        print(f"更新時刻     : {update_time}")

        for policy in report.get("osPolicyCompliances", []):
            state = policy.get("complianceState", "UNKNOWN")
            print(f"状態         : {state}")

            for resource in policy.get("osPolicyResourceCompliances", []):
                exec_output = resource.get("execResourceOutput", {})
                raw = exec_output.get("enforcementOutput", "")
                if raw:
                    try:
                        output = base64.b64decode(raw).decode("utf-8", errors="replace")
                        print()
                        print("--- コマンド出力 ---")
                        print(output.rstrip())
                        print("--------------------")
                    except Exception:
                        print(f"出力 (raw): {raw}")
        print()


def run_command(
    zone: str,
    command: str,
    label_key: str | None = None,
    label_value: str | None = None,
    instance_id: str | None = None,
) -> None:
    try:
        project_id = _get_project_id()
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    assignment_id = f"cmd-{uuid.uuid4().hex[:8]}"

    # インスタンスID 指定時は一時ラベルを付与してフィルタリングに使用
    instance_name = None
    if instance_id:
        try:
            instance_name = _resolve_instance_name(instance_id, project_id, zone)
        except Exception as e:
            print(f"エラー: インスタンスの解決に失敗しました: {e}", file=sys.stderr)
            sys.exit(1)
        temp_label_value = uuid.uuid4().hex[:8]
        label_key = _TEMP_LABEL_KEY
        label_value = temp_label_value
        try:
            _add_temp_label(instance_name, temp_label_value, project_id, zone)
        except Exception as e:
            print(f"エラー: 一時ラベルの付与に失敗しました: {e}", file=sys.stderr)
            sys.exit(1)

    print("[OS Config] コマンドを送信します")
    print(f"  プロジェクト  : {project_id}")
    print(f"  ゾーン        : {zone}")
    print(f"  Assignment ID : {assignment_id}")
    print(f"  コマンド      : {command}")
    if instance_id:
        print(f"  対象インスタンス: {instance_name} ({instance_id})")
    else:
        print(f"  対象ラベル    : {label_key}={label_value}")
    print()

    yaml_content = _build_policy_yaml(command, label_key, label_value)

    try:
        print("  ロールアウト完了まで待機中...")
        _create_assignment(assignment_id, zone, yaml_content, project_id)
        print("  ロールアウト完了")
    except Exception as e:
        if instance_name:
            _remove_temp_label(instance_name, project_id, zone)
        print(f"エラー: Assignment の作成に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    # 実行結果を取得
    reports = _fetch_reports(assignment_id, zone, project_id)

    # Assignment を削除 (ジョブを残さない)
    _delete_assignment(assignment_id, zone, project_id)

    # 一時ラベルを削除
    if instance_name:
        _remove_temp_label(instance_name, project_id, zone)

    if reports:
        _print_reports(reports)
    else:
        print()
        print("  実行結果のレポートが取得できませんでした。")
        print("  VM マネージャー > ポリシーの適用状況 で確認してください。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="gcloud サブプロセスで OS Config コマンドを送信し結果を取得する"
    )
    parser.add_argument(
        "--zone",
        default=os.environ.get("GOOGLE_CLOUD_ZONE", "asia-northeast1-a"),
        help="ゾーン名 (デフォルト: 環境変数 GOOGLE_CLOUD_ZONE または asia-northeast1-a)",
    )
    parser.add_argument(
        "--command",
        default=_DEFAULT_COMMAND,
        help=f"実行するシェルコマンド (デフォルト: {_DEFAULT_COMMAND})",
    )

    # インスタンスID またはラベルのいずれかを必須にする
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--instance-id",
        help="対象インスタンス名または数値ID (例: {インスタンスID}, 6733133130176916850)",
    )
    target.add_argument(
        "--label",
        metavar="KEY=VALUE",
        help="対象ラベル KEY=VALUE 形式 (例: managed-by=osconfig)",
    )

    args = parser.parse_args()

    if args.label:
        if "=" not in args.label:
            parser.error("--label は KEY=VALUE 形式で指定してください (例: managed-by=osconfig)")
        label_key, label_value = args.label.split("=", 1)
        instance_id = None
    else:
        label_key = None
        label_value = None
        instance_id = args.instance_id

    run_command(
        zone=args.zone,
        command=args.command,
        label_key=label_key,
        label_value=label_value,
        instance_id=instance_id,
    )
