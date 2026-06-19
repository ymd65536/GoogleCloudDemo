"""
google-api-python-client を使って OS Config で GCE インスタンスにコマンドを送信するスクリプト

OSPolicyAssignment + ExecResource を利用して、ラベル managed-by=osconfig の
インスタンスにシェルコマンドを送信し、実行履歴を Cloud Logging に記録します。

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_ZONE=asia-northeast1-a

    # デフォルト: /tmp にテキストファイルを作成
    python send_command.py

    # コマンドを指定
    python send_command.py --command "df -h"

    # ゾーン・Assignment ID を指定
    python send_command.py --zone asia-northeast1-b --assignment-id my-cmd-01

必要な権限:
    - roles/osconfig.osPolicyAssignmentAdmin (作成・削除)
    - roles/logging.logWriter (Cloud Logging への書き込み)
"""

import argparse
import datetime
import os
import time
import uuid

import google.auth
import google.auth.transport.requests
from googleapiclient import discovery

# Cloud Logging のログ名
_LOG_NAME = "osconfig-command-history"

# デフォルトで送信するコマンド
_DEFAULT_COMMAND = 'echo "Created by OS Config at $(date)" > /tmp/osconfig_result.txt'

# インスタンスのフィルタリングに使うラベル
_MANAGED_LABEL_KEY = "managed-by"
_MANAGED_LABEL_VALUE = "osconfig"

# LRO ポーリング間隔 (秒)
_POLL_INTERVAL = 10


def _build_assignment_body(command: str, label_key: str, label_value: str) -> dict:
    """OS Policy Assignment の REST リクエストボディを組み立てる。"""
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
        "instanceFilter": {
            "inclusionLabels": [{"labels": {label_key: label_value}}]
        },
        "rollout": {
            "disruptionBudget": {"percent": 100},
            "minWaitDuration": "0s",
        },
    }


def _wait_for_operation(
    credentials: google.auth.credentials.Credentials, operation_name: str
) -> dict:
    """LRO が完了するまでポーリングし、レスポンス (OSPolicyAssignment) を返す。"""
    session = google.auth.transport.requests.AuthorizedSession(credentials)
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


def _log_to_cloud_logging(
    credentials: google.auth.credentials.Credentials,
    project_id: str,
    payload: dict,
) -> None:
    """Cloud Logging (v2) にログエントリを書き込む。"""
    service = discovery.build("logging", "v2", credentials=credentials)
    body = {
        "entries": [
            {
                "logName": f"projects/{project_id}/logs/{_LOG_NAME}",
                "resource": {
                    "type": "global",
                    "labels": {"project_id": project_id},
                },
                "severity": "INFO",
                "jsonPayload": payload,
            }
        ]
    }
    service.entries().write(body=body).execute()


def send_command(
    zone: str,
    command: str,
    assignment_id: str,
    label_key: str = _MANAGED_LABEL_KEY,
    label_value: str = _MANAGED_LABEL_VALUE,
) -> dict:
    """OS Config で対象インスタンスにコマンドを送信し Cloud Logging に記録する。"""
    credentials, project_id = google.auth.default()
    if not project_id:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise ValueError("環境変数 GOOGLE_CLOUD_PROJECT が設定されていません")

    service = discovery.build("osconfig", "v1", credentials=credentials)
    parent = f"projects/{project_id}/locations/{zone}"

    print("[OS Config] コマンドを送信します")
    print(f"  プロジェクト  : {project_id}")
    print(f"  ゾーン        : {zone}")
    print(f"  Assignment ID : {assignment_id}")
    print(f"  コマンド      : {command}")
    print(f"  対象ラベル    : {label_key}={label_value}")
    print()

    body = _build_assignment_body(command, label_key, label_value)

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

    assignment = _wait_for_operation(credentials, operation["name"])

    rollout_state = assignment.get("rolloutState", "UNKNOWN")
    resource_name = assignment.get(
        "name", f"{parent}/osPolicyAssignments/{assignment_id}"
    )

    print(f"  送信完了     : {resource_name}")
    print(f"  ロールアウト : {rollout_state}")
    print()

    # Cloud Logging に記録
    _log_to_cloud_logging(
        credentials,
        project_id,
        {
            "assignment_id": assignment_id,
            "command": command,
            "zone": zone,
            "label": f"{label_key}={label_value}",
            "rollout_state": rollout_state,
            "resource_name": resource_name,
            "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    )
    print(f"  Cloud Logging に記録しました (ログ名: {_LOG_NAME})")

    return assignment


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="google-api-python-client で OS Config コマンドを送信する"
    )
    parser.add_argument(
        "--zone",
        default=os.environ.get("GOOGLE_CLOUD_ZONE", "asia-northeast1-a"),
        help="ゾーン名 (デフォルト: 環境変数 GOOGLE_CLOUD_ZONE または asia-northeast1-a)",
    )
    parser.add_argument(
        "--command",
        default=_DEFAULT_COMMAND,
        help="実行するシェルコマンド",
    )
    parser.add_argument(
        "--assignment-id",
        default=None,
        help="OSPolicyAssignment の ID (省略時は自動生成)",
    )
    parser.add_argument(
        "--label-key",
        default=_MANAGED_LABEL_KEY,
        help=f"対象インスタンスのラベルキー (デフォルト: {_MANAGED_LABEL_KEY})",
    )
    parser.add_argument(
        "--label-value",
        default=_MANAGED_LABEL_VALUE,
        help=f"対象インスタンスのラベル値 (デフォルト: {_MANAGED_LABEL_VALUE})",
    )
    args = parser.parse_args()

    assignment_id = args.assignment_id or f"cmd-{uuid.uuid4().hex[:8]}"

    result = send_command(
        zone=args.zone,
        command=args.command,
        assignment_id=assignment_id,
        label_key=args.label_key,
        label_value=args.label_value,
    )

    print()
    print("=" * 60)
    print("完了サマリー")
    print(f"  Assignment ID : {assignment_id}")
    print(f"  ゾーン        : {args.zone}")
    print(f"  コマンド      : {args.command}")
    print(f"  ロールアウト  : {result.get('rolloutState', 'UNKNOWN')}")
    print()
    print("不要になったら削除してください:")
    print(
        f"  gcloud osconfig os-policy-assignments delete {assignment_id} --location={args.zone}"
    )
