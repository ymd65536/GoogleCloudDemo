"""
OS Config で GCE インスタンスにコマンドを送信し、実行結果を取得するスクリプト

- OSPolicyAssignment + ExecResource でコマンドを送信
- 実行結果 (osPolicyAssignmentReports.enforcementOutput) を取得して表示
- 完了後に Assignment を自動削除 (ジョブを残さない)
- Cloud Logging への書き込みなし
- デフォルトコマンド: df -h (ディスク使用量)
- インスタンスID またはラベル指定が必須

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id

    # インスタンスID で指定
    python run_command.py --instance-id {インスタンスID}

    # ラベルで指定 (KEY=VALUE 形式)
    python run_command.py --label managed-by=osconfig

    # コマンドを指定
    python run_command.py --instance-id {インスタンスID} --command "free -h"

必要な権限:
    - roles/osconfig.osPolicyAssignmentAdmin (作成・削除)
"""

import argparse
import base64
import os
import sys
import time
import uuid
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

# デフォルトコマンド: ディスク使用量
_DEFAULT_COMMAND = "df -h"

# ポーリング間隔 (秒)
_POLL_INTERVAL = 5

# レポート取得の最大待機時間 (秒) - OS Config エージェントの実行ラグを考慮
_REPORT_WAIT_SECONDS = 180

# インスタンスID 指定時に付与する一時ラベルのキー
_TEMP_LABEL_KEY = "osconfig-tmp-target"


def _build_service(credentials):
    """SSL 証明書を指定した httplib2 経由で osconfig サービスを構築する。"""
    authorized_http = google_auth_httplib2.AuthorizedHttp(
        credentials, http=httplib2.Http(ca_certs=_CA_BUNDLE)
    )
    return discovery.build("osconfig", "v1", http=authorized_http)


def _build_compute_service(credentials):
    """SSL 証明書を指定した httplib2 経由で compute サービスを構築する。"""
    authorized_http = google_auth_httplib2.AuthorizedHttp(
        credentials, http=httplib2.Http(ca_certs=_CA_BUNDLE)
    )
    return discovery.build("compute", "v1", http=authorized_http)


def _resolve_instance_name(compute, project_id: str, zone: str, instance_id_or_name: str) -> str:
    """数値IDまたはインスタンス名を受け取り、インスタンス名を返す。
    数値IDの場合はゾーン内のインスタンス一覧から検索して名前を解決する。
    """
    # 数値IDかどうかを判定
    if not instance_id_or_name.isdigit():
        return instance_id_or_name  # すでに名前

    numeric_id = instance_id_or_name
    print(f"  数値ID {numeric_id} からインスタンス名を解決中...")
    result = compute.instances().list(project=project_id, zone=zone).execute()
    for inst in result.get("items", []):
        if str(inst.get("id", "")) == numeric_id:
            name = inst["name"]
            print(f"  インスタンス名: {name}")
            return name
    raise ValueError(
        f"ゾーン {zone} に数値ID {numeric_id} のインスタンスが見つかりませんでした"
    )


def _add_temp_label(compute, project_id: str, zone: str, instance_id: str, label_value: str) -> None:
    """インスタンスに一時ラベルを付与する。"""
    inst = compute.instances().get(project=project_id, zone=zone, instance=instance_id).execute()
    labels = inst.get("labels", {})
    labels[_TEMP_LABEL_KEY] = label_value
    compute.instances().setLabels(
        project=project_id, zone=zone, instance=instance_id,
        body={"labels": labels, "labelFingerprint": inst["labelFingerprint"]},
    ).execute()
    print(f"  一時ラベルを付与しました: {_TEMP_LABEL_KEY}={label_value}")


def _remove_temp_label(compute, project_id: str, zone: str, instance_id: str) -> None:
    """インスタンスから一時ラベルを削除する。"""
    try:
        inst = compute.instances().get(project=project_id, zone=zone, instance=instance_id).execute()
        labels = inst.get("labels", {})
        labels.pop(_TEMP_LABEL_KEY, None)
        compute.instances().setLabels(
            project=project_id, zone=zone, instance=instance_id,
            body={"labels": labels, "labelFingerprint": inst["labelFingerprint"]},
        ).execute()
        print(f"  一時ラベルを削除しました: {_TEMP_LABEL_KEY}")
    except Exception as e:
        print(f"  警告: 一時ラベルの削除に失敗しました: {e}", file=sys.stderr)


def _build_assignment_body(
    command: str,
    label_key: str,
    label_value: str,
) -> dict:
    """OS Policy Assignment のリクエストボディを組み立てる。"""
    instance_filter = {"inclusionLabels": [{"labels": {label_key: label_value}}]}
    return {
        "osPolicies": [
            {
                "id": "exec-command-policy",
                "mode": "ENFORCEMENT",
                "resourceGroups": [
                    {
                        "resources": [
                            {
                                "id": "run-command",
                                "exec": {
                                    "validate": {
                                        "interpreter": "SHELL",
                                        "script": "exit 101",
                                    },
                                    "enforce": {
                                        "interpreter": "SHELL",
                                        "script": f"{command}\nexit 100",
                                    },
                                },
                            }
                        ]
                    }
                ],
            }
        ],
        "instanceFilter": instance_filter,
        "rollout": {
            "disruptionBudget": {"percent": 100},
            "minWaitDuration": "0s",
        },
    }


def _wait_for_lro(credentials: google.auth.credentials.Credentials, operation_name: str) -> dict:
    """LRO が完了するまでポーリングし OSPolicyAssignment を返す。"""
    session = google.auth.transport.requests.AuthorizedSession(credentials)
    session.verify = _CA_BUNDLE
    url = f"https://osconfig.googleapis.com/v1/{operation_name}"
    while True:
        resp = session.get(url)
        resp.raise_for_status()
        op = resp.json()
        if op.get("done"):
            if "error" in op:
                raise RuntimeError(f"LRO が失敗しました: {op['error']}")
            return op.get("response", {})
        time.sleep(_POLL_INTERVAL)


def _fetch_reports(service, project_id: str, zone: str, assignment_id: str) -> list:
    """osPolicyAssignmentReports からレポートを取得する (最大 _REPORT_WAIT_SECONDS 秒待機)。"""
    parent = (
        f"projects/{project_id}/locations/{zone}"
        f"/instances/-/osPolicyAssignments/{assignment_id}"
    )
    print("  実行結果を取得中", end="", flush=True)
    last_error = None
    for _ in range(_REPORT_WAIT_SECONDS // _POLL_INTERVAL):
        time.sleep(_POLL_INTERVAL)
        print(".", end="", flush=True)
        try:
            resp = (
                service.projects()
                .locations()
                .instances()
                .osPolicyAssignments()
                .reports()
                .list(parent=parent)
                .execute()
            )
            reports = resp.get("osPolicyAssignmentReports", [])
            if reports:
                print()
                return reports
        except Exception as e:
            last_error = e
    print()
    if last_error:
        print(f"  警告: レポート取得中にエラーが発生しました: {last_error}", file=sys.stderr)
    return []


def _delete_assignment(service, project_id: str, zone: str, assignment_id: str) -> None:
    """Assignment を削除する (ジョブを残さない)。"""
    name = f"projects/{project_id}/locations/{zone}/osPolicyAssignments/{assignment_id}"
    try:
        service.projects().locations().osPolicyAssignments().delete(name=name).execute()
        print(f"  Assignment を削除しました: {assignment_id}")
    except Exception as e:
        print(f"  警告: Assignment の削除に失敗しました: {e}", file=sys.stderr)


def _print_reports(reports: list) -> None:
    """レポートの実行結果 (stdout) を表示する。"""
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
    credentials, project_id = google.auth.default()
    if not project_id:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        print("環境変数 GOOGLE_CLOUD_PROJECT が設定されていません", file=sys.stderr)
        sys.exit(1)

    service = _build_service(credentials)
    parent = f"projects/{project_id}/locations/{zone}"
    assignment_id = f"cmd-{uuid.uuid4().hex[:8]}"

    # インスタンスID 指定時は一時ラベルを付与してフィルタリングに使用
    if instance_id:
        compute = _build_compute_service(credentials)
        try:
            instance_name = _resolve_instance_name(compute, project_id, zone, instance_id)
        except Exception as e:
            print(f"エラー: インスタンスの解決に失敗しました: {e}", file=sys.stderr)
            sys.exit(1)
        temp_label_value = uuid.uuid4().hex[:8]
        label_key = _TEMP_LABEL_KEY
        label_value = temp_label_value
        try:
            _add_temp_label(compute, project_id, zone, instance_name, temp_label_value)
        except Exception as e:
            print(f"エラー: 一時ラベルの付与に失敗しました: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        compute = None
        instance_name = None

    print("[OS Config] コマンドを送信します")
    print(f"  プロジェクト  : {project_id}")
    print(f"  ゾーン        : {zone}")
    print(f"  Assignment ID : {assignment_id}")
    print(f"  コマンド      : {command}")
    if instance_id:
        print(f"  対象インスタンス: {instance_id}")
    else:
        print(f"  対象ラベル    : {label_key}={label_value}")
    print()

    body = _build_assignment_body(command, label_key, label_value)

    try:
        operation = (
            service.projects()
            .locations()
            .osPolicyAssignments()
            .create(parent=parent, osPolicyAssignmentId=assignment_id, body=body)
            .execute()
        )
    except Exception as e:
        if compute and instance_name:
            _remove_temp_label(compute, project_id, zone, instance_name)
        print(f"エラー: Assignment の作成に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    print("  ロールアウト完了まで待機中...")
    _wait_for_lro(credentials, operation["name"])
    print("  ロールアウト完了")

    # 実行結果を取得
    reports = _fetch_reports(service, project_id, zone, assignment_id)

    # Assignment を削除 (ジョブを残さない)
    _delete_assignment(service, project_id, zone, assignment_id)

    # 一時ラベルを削除
    if compute and instance_name:
        _remove_temp_label(compute, project_id, zone, instance_name)

    if reports:
        _print_reports(reports)
    else:
        print()
        print("  実行結果のレポートが取得できませんでした。")
        print("  VM マネージャー > ポリシーの適用状況 で確認してください。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="OS Config でコマンドを送信し結果を取得する (Assignment は自動削除)"
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
        help="対象インスタンスID (例: {インスタンスID})",
    )
    target.add_argument(
        "--label",
        metavar="KEY=VALUE",
        help="対象ラベル・KEY=VALUE 形式 (例: managed-by=osconfig)",
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
