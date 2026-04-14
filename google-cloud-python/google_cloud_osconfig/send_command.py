"""
OS Config を使って GCE インスタンスにコマンドを送信するスクリプト

OSPolicyAssignment + ExecResource を利用して、ラベル managed-by=osconfig の
インスタンスにシェルコマンドを送信し、実行履歴を Cloud Logging に記録します。

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_ZONE=asia-northeast1-a

    # デフォルト: ホームディレクトリにテキストファイルを作成
    python send_command.py

    # コマンドを指定
    python send_command.py --command "df -h"

    # ゾーン指定
    python send_command.py --zone asia-northeast1-b --command "uptime"

必要な権限:
    - roles/osconfig.osPolicyAssignmentAdmin (作成・削除)
    - roles/logging.logWriter (Cloud Logging への書き込み)
"""

import argparse
import datetime
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import logging as gcp_logging, osconfig_v1
from google.protobuf import duration_pb2

from gcp_auth import _get_credentials, _get_project_id

# Cloud Logging のログ名
_LOG_NAME = "osconfig-command-history"

# デフォルトで送信するコマンド: /tmp にテキストファイルを作成 (~ は OS Config 実行環境で展開されない場合がある)
_DEFAULT_COMMAND = 'echo "Created by OS Config at $(date)" > /tmp/osconfig_result.txt'

# インスタンスのフィルタリングに使うラベル
_MANAGED_LABEL_KEY = "managed-by"
_MANAGED_LABEL_VALUE = "osconfig"


def _get_logger():
    """Cloud Logging のロガーを返す (HTTP transport)。"""
    project_id = _get_project_id()
    client = gcp_logging.Client(
        project=project_id,
        credentials=_get_credentials(),
        _use_grpc=False,
    )
    return client.logger(_LOG_NAME)


def _build_exec_resource(command: str) -> osconfig_v1.OSPolicy.Resource:
    """シェルコマンドを実行する ExecResource を組み立てる。"""
    validate_exec = osconfig_v1.OSPolicy.Resource.ExecResource.Exec(
        interpreter=osconfig_v1.OSPolicy.Resource.ExecResource.Exec.Interpreter.SHELL,
        script="exit 101",
    )
    enforce_exec = osconfig_v1.OSPolicy.Resource.ExecResource.Exec(
        interpreter=osconfig_v1.OSPolicy.Resource.ExecResource.Exec.Interpreter.SHELL,
        script=f"{command}\nexit 100",
    )
    return osconfig_v1.OSPolicy.Resource(
        id="run-command",
        exec=osconfig_v1.OSPolicy.Resource.ExecResource(
            validate=validate_exec,
            enforce=enforce_exec,
        ),
    )


def send_command(
    zone: str,
    command: str,
    assignment_id: str,
    label_key: str = _MANAGED_LABEL_KEY,
    label_value: str = _MANAGED_LABEL_VALUE,
) -> osconfig_v1.OSPolicyAssignment:
    """指定ラベルを持つインスタンスにコマンドを送信し、Cloud Logging に記録する。"""
    project_id = _get_project_id()
    client = osconfig_v1.OsConfigZonalServiceClient(
        credentials=_get_credentials(),
        transport="rest",
    )

    parent = f"projects/{project_id}/locations/{zone}"

    os_policy = osconfig_v1.OSPolicy(
        id="exec-command-policy",
        mode=osconfig_v1.OSPolicy.Mode.ENFORCEMENT,
        resource_groups=[
            osconfig_v1.OSPolicy.ResourceGroup(
                resources=[_build_exec_resource(command)]
            )
        ],
    )

    instance_filter = osconfig_v1.OSPolicyAssignment.InstanceFilter(
        inclusion_labels=[
            osconfig_v1.OSPolicyAssignment.LabelSet(
                labels={label_key: label_value}
            )
        ]
    )

    rollout = osconfig_v1.OSPolicyAssignment.Rollout(
        disruption_budget=osconfig_v1.FixedOrPercent(percent=100),
        min_wait_duration=duration_pb2.Duration(seconds=0),
    )

    os_policy_assignment = osconfig_v1.OSPolicyAssignment(
        os_policies=[os_policy],
        instance_filter=instance_filter,
        rollout=rollout,
    )

    print(f"[OS Config] コマンドを送信します")
    print(f"  プロジェクト  : {project_id}")
    print(f"  ゾーン        : {zone}")
    print(f"  Assignment ID : {assignment_id}")
    print(f"  コマンド      : {command}")
    print(f"  対象ラベル    : {label_key}={label_value}")
    print()

    operation = client.create_os_policy_assignment(
        request=osconfig_v1.CreateOSPolicyAssignmentRequest(
            parent=parent,
            os_policy_assignment=os_policy_assignment,
            os_policy_assignment_id=assignment_id,
        )
    )
    print("  作成中... (LRO 完了まで待機)")
    result = operation.result()

    print(f"  送信完了     : {result.name}")
    print(f"  ロールアウト : {result.rollout_state.name}")
    print()

    # Cloud Logging に記録
    logger = _get_logger()
    logger.log_struct(
        {
            "assignment_id": assignment_id,
            "command": command,
            "zone": zone,
            "label": f"{label_key}={label_value}",
            "rollout_state": result.rollout_state.name,
            "resource_name": result.name,
            "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
        severity="INFO",
    )
    print(f"  Cloud Logging に記録しました (ログ名: {_LOG_NAME})")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="OS Config で GCE インスタンスにコマンドを送信する"
    )
    parser.add_argument(
        "--zone",
        default=os.environ.get("GOOGLE_CLOUD_ZONE", "asia-northeast1-a"),
        help="ゾーン名 (デフォルト: 環境変数 GOOGLE_CLOUD_ZONE または asia-northeast1-a)",
    )
    parser.add_argument(
        "--command",
        default=_DEFAULT_COMMAND,
        help="実行するシェルコマンド (デフォルト: ホームディレクトリにテキストファイルを作成)",
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
    print(f"  ロールアウト  : {result.rollout_state.name}")
    print()
    print("不要になったら削除してください:")
    print(f"  python os_policy_assignment.py --delete {assignment_id} --zone {args.zone}")
