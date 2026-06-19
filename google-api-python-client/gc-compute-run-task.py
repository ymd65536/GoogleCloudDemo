import argparse
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
import google_auth_httplib2
import httplib2
from googleapiclient import discovery

# デフォルト設定
_DEFAULT_COMMAND = "df -h"
_MANAGED_LABEL_KEY = "managed-by"
_MANAGED_LABEL_VALUE = "osconfig"

# ポーリング間隔 (秒)
_POLL_INTERVAL = 5


def _build_assignment_body(
    command: str,
    label_key: str | None,
    label_value: str | None,
    zone: str | None = None,
    instance_id: str | None = None,
) -> dict:
    """OS Policy Assignment の REST リクエストボディを組み立てる。

    label_key / label_value が指定された場合はラベルで絞り込む。
    指定されていない場合は zone + instance_id でインスタンスを直接指定する。
    """
    if instance_id and zone:
        instance_filter = {
            "instances": [f"zones/{zone}/instances/{instance_id}"]
        }
    else:
        instance_filter = {
            "inclusionLabels": [{"labels": {label_key: label_value}}]
        }
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


def _wait_for_operation(
    credentials: google.auth.credentials.Credentials, operation_name: str
) -> dict:
    """LRO が完了するまでポーリングし OSPolicyAssignment を返す。"""
    import google.auth.transport.requests

    session = google.auth.transport.requests.AuthorizedSession(credentials)
    session.verify = _CA_BUNDLE
    url = f"https://osconfig.googleapis.com/v1/{operation_name}"

    print("  作成中... (LRO 完了まで待機)")
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
    """osPolicyAssignmentReports からインスタンスごとの実行結果を取得する。
    レポートが揃うまで最大 60 秒ポーリングする。
    """
    parent = (
        f"projects/{project_id}/locations/{zone}"
        f"/instances/-/osPolicyAssignments/{assignment_id}"
    )
    print("  実行結果を取得中... (レポート反映まで最大60秒待機)")
    for _ in range(12):  # 5秒 × 12 = 最大60秒
        time.sleep(5)
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
                return reports
        except Exception:
            pass
    return []


def _print_reports(reports: list) -> None:
    """インスタンスごとの実行結果を表示する。"""
    print()
    print("=" * 60)
    print("インスタンス実行結果")
    print("=" * 60)
    for report in reports:
        instance = report.get("instance", "").split("/")[-1]
        update_time = report.get("updateTime", "")
        print(f"  インスタンス : {instance}")
        print(f"  更新時刻     : {update_time}")
        for policy in report.get("osPolicyCompliances", []):
            state = policy.get("complianceState", "UNKNOWN")
            print(f"  コンプライアンス: {state}")
            for resource in policy.get("osPolicyResourceCompliances", []):
                rid = resource.get("osPolicyResourceId", "")
                rstate = resource.get("complianceState", "UNKNOWN")
                exec_output = resource.get("execResourceOutput", {})
                enforce_out = exec_output.get("enforcementOutput", "")
                print(f"    リソース [{rid}]: {rstate}")
                if enforce_out:
                    print(f"    出力         : {enforce_out}")
        print()


def execute_osconfig_task(
    zone: str,
    command: str,
    label_key: str | None = None,
    label_value: str | None = None,
    instance_id: str | None = None,
):
    """OS Config の Task Job を作成して実行する"""
    credentials, project_id = google.auth.default()
    if not project_id:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        print("環境変数 GOOGLE_CLOUD_PROJECT が設定されていません", file=sys.stderr)
        sys.exit(1)

    authorized_http = google_auth_httplib2.AuthorizedHttp(
        credentials, http=httplib2.Http(ca_certs=_CA_BUNDLE)
    )
    service = discovery.build("osconfig", "v1", http=authorized_http)
    parent = f"projects/{project_id}/locations/{zone}"

    # ユニークな Assignment ID を生成
    assignment_id = f"cmd-{uuid.uuid4().hex[:8]}"

    print("[OS Config] コマンドを送信します")
    print(f"  プロジェクト  : {project_id}")
    print(f"  ゾーン        : {zone}")
    print(f"  Assignment ID : {assignment_id}")
    print(f"  コマンド      : {command}")
    if instance_id:
        print(f"  対象インスタンス: {instance_id}\n")
    else:
        print(f"  対象ラベル    : {label_key}={label_value}\n")

    body = _build_assignment_body(command, label_key, label_value, zone=zone, instance_id=instance_id)

    try:
        operation = (
            service.projects()
            .locations()
            .osPolicyAssignments()
            .create(
                parent=parent,
                osPolicyAssignmentId=assignment_id,
                body=body,
            )
            .execute()
        )
    except Exception as e:
        print(f"エラー: Assignment の作成に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    # LRO 完了を待機
    assignment = _wait_for_operation(credentials, operation["name"])

    rollout_state = assignment.get("rolloutState", "UNKNOWN")
    resource_name = assignment.get("name", f"{parent}/osPolicyAssignments/{assignment_id}")

    print(f"  送信完了     : {resource_name}")
    print(f"  ロールアウト : {rollout_state}")

    # インスタンスごとの実行結果を取得して表示
    reports = _fetch_reports(service, project_id, zone, assignment_id)
    if reports:
        _print_reports(reports)
    else:
        print()
        print("  (レポートがまだ反映されていません。しばらく後に Cloud Logging または")
        print("   コンソールの VM マネージャー > ポリシーの適用状況で確認してください)")
    print()
    print("不要になったら削除してください:")
    print(f"  gcloud compute os-config os-policy-assignments delete {assignment_id} --location={zone}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OS Config Task Jobs でコマンドを一斉実行する")
    parser.add_argument(
        "--zone",
        default=os.environ.get("GOOGLE_CLOUD_ZONE", "asia-northeast1-a"),
        help="ゾーン名 (デフォルト: asia-northeast1-a)",
    )
    parser.add_argument(
        "--command",
        default=_DEFAULT_COMMAND,
        help=f"実行するシェルコマンド (デフォルト: {_DEFAULT_COMMAND})",
    )
    parser.add_argument(
        "--label-key",
        default=None,
        help=f"対象インスタンスのラベルキー (デフォルト: {_MANAGED_LABEL_KEY}、--instance-id 未指定時に使用)",
    )
    parser.add_argument(
        "--label-value",
        default=None,
        help=f"対象インスタンスのラベル値 (デフォルト: {_MANAGED_LABEL_VALUE}、--instance-id 未指定時に使用)",
    )
    parser.add_argument(
        "--instance-id",
        default=None,
        help="対象インスタンスID (指定した場合はラベルより優先される)",
    )
    args = parser.parse_args()

    # インスタンスID未指定の場合はデフォルトラベルにフォールバック
    if args.instance_id:
        label_key = None
        label_value = None
    else:
        label_key = args.label_key or _MANAGED_LABEL_KEY
        label_value = args.label_value or _MANAGED_LABEL_VALUE

    execute_osconfig_task(
        zone=args.zone,
        command=args.command,
        label_key=label_key,
        label_value=label_value,
        instance_id=args.instance_id,
    )
