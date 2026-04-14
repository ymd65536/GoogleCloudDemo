"""
google-cloud-osconfig を使って GCE インスタンスにコマンドを送信するサンプル

OS Config の OSPolicyAssignment + ExecResource を利用して、
ラベルで絞り込んだ GCE インスタンス群にシェルコマンドを送信します。

インストール:
    pip install google-cloud-os-config

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_ZONE=asia-northeast1-a   # 省略時は asia-northeast1-a
    python os_policy_assignment.py --command "echo hello"
    python os_policy_assignment.py --command "df -h" --label-key env --label-value dev
    python os_policy_assignment.py --list
    python os_policy_assignment.py --delete <assignment-id>

必要な権限:
    - roles/osconfig.osPolicyAssignmentAdmin (作成・削除)
    - roles/osconfig.osPolicyAssignmentViewer (一覧表示)

注意:
    GCE インスタンス側に OS Config エージェントが起動していること。
    Debian/Ubuntu: sudo systemctl status google-osconfig-agent
    ExecResource の終了コード:
      100 → 既に望ましい状態 (以降の enforce フェーズをスキップ)
      101 → 望ましい状態ではない (enforce フェーズを実行)
      その他 → エラー
"""

import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import osconfig_v1
from google.protobuf import duration_pb2

from gcp_auth import _get_credentials, _get_project_id


def _build_exec_resource(
    resource_id: str,
    command: str,
) -> osconfig_v1.OSPolicy.Resource:
    """シェルコマンドを実行する ExecResource を作成する。

    validate フェーズ: 常に exit 101 を返し、enforce フェーズを必ず実行させる。
    enforce フェーズ: 指定されたコマンドを実行し exit 100 を返す。
    """
    # validate: 常に enforce フェーズを実行させる (exit 101)
    validate_exec = osconfig_v1.OSPolicy.Resource.ExecResource.Exec(
        interpreter=osconfig_v1.OSPolicy.Resource.ExecResource.Exec.Interpreter.SHELL,
        script="exit 101",
    )

    # enforce: 指定コマンドを実行し成功を返す (exit 100)
    enforce_script = f"{command}\nexit 100"
    enforce_exec = osconfig_v1.OSPolicy.Resource.ExecResource.Exec(
        interpreter=osconfig_v1.OSPolicy.Resource.ExecResource.Exec.Interpreter.SHELL,
        script=enforce_script,
    )

    exec_resource = osconfig_v1.OSPolicy.Resource.ExecResource(
        validate=validate_exec,
        enforce=enforce_exec,
    )

    return osconfig_v1.OSPolicy.Resource(
        id=resource_id,
        exec=exec_resource,
    )


def send_command(
    zone: str,
    command: str,
    assignment_id: str | None = None,
    label_key: str | None = None,
    label_value: str | None = None,
) -> osconfig_v1.OSPolicyAssignment:
    """指定コマンドを GCE インスタンスに送信する OSPolicyAssignment を作成する。

    Args:
        zone: ターゲットゾーン (例: asia-northeast1-a)
        command: 実行するシェルコマンド
        assignment_id: OSPolicyAssignment の ID (省略時は自動生成)
        label_key: インスタンスフィルター用のラベルキー
        label_value: インスタンスフィルター用のラベル値

    Returns:
        作成された OSPolicyAssignment オブジェクト
    """
    project_id = _get_project_id()
    client = osconfig_v1.OsConfigZonalServiceClient(
        credentials=_get_credentials(),
        transport="rest",
    )

    parent = f"projects/{project_id}/locations/{zone}"
    policy_assignment_id = assignment_id or f"cmd-{uuid.uuid4().hex[:8]}"

    # --- ExecResource を含む OSPolicy を定義 ---
    resource = _build_exec_resource(
        resource_id="run-command",
        command=command,
    )

    resource_group = osconfig_v1.OSPolicy.ResourceGroup(resources=[resource])

    os_policy = osconfig_v1.OSPolicy(
        id="exec-command-policy",
        mode=osconfig_v1.OSPolicy.Mode.ENFORCEMENT,
        resource_groups=[resource_group],
    )

    # --- インスタンスフィルターを定義 ---
    if label_key and label_value:
        label_set = osconfig_v1.OSPolicyAssignment.LabelSet(
            labels={label_key: label_value}
        )
        instance_filter = osconfig_v1.OSPolicyAssignment.InstanceFilter(
            inclusion_labels=[label_set]
        )
    else:
        # フィルターなし: ゾーン内の全インスタンスを対象にする
        instance_filter = osconfig_v1.OSPolicyAssignment.InstanceFilter(
            all=True
        )

    # --- ロールアウト設定 (一度に 100% 展開) ---
    rollout = osconfig_v1.OSPolicyAssignment.Rollout(
        disruption_budget=osconfig_v1.FixedOrPercent(percent=100),
        min_wait_duration=duration_pb2.Duration(seconds=0),
    )

    # --- OSPolicyAssignment を作成 ---
    os_policy_assignment = osconfig_v1.OSPolicyAssignment(
        os_policies=[os_policy],
        instance_filter=instance_filter,
        rollout=rollout,
    )

    request = osconfig_v1.CreateOSPolicyAssignmentRequest(
        parent=parent,
        os_policy_assignment=os_policy_assignment,
        os_policy_assignment_id=policy_assignment_id,
    )

    print(f"[OS Config] OSPolicyAssignment を作成します")
    print(f"  プロジェクト : {project_id}")
    print(f"  ゾーン       : {zone}")
    print(f"  Assignment ID: {policy_assignment_id}")
    print(f"  コマンド     : {command}")
    if label_key and label_value:
        print(f"  対象ラベル   : {label_key}={label_value}")
    else:
        print(f"  対象         : ゾーン内全インスタンス")
    print()

    # LRO (Long Running Operation) を開始し、完了まで待機
    operation = client.create_os_policy_assignment(request=request)
    print("  作成中... (LRO 完了まで待機)")
    result = operation.result()

    print(f"  作成完了: {result.name}")
    print(f"  ロールアウト状態: {result.rollout_state.name}")
    return result


def list_assignments(zone: str) -> None:
    """指定ゾーンの OSPolicyAssignment 一覧を表示する。"""
    project_id = _get_project_id()
    client = osconfig_v1.OsConfigZonalServiceClient(
        credentials=_get_credentials(),
        transport="rest",
    )

    parent = f"projects/{project_id}/locations/{zone}"

    print(f"[OS Config] OSPolicyAssignment 一覧 ({zone})")
    print("-" * 60)

    assignments = list(
        client.list_os_policy_assignments(
            request=osconfig_v1.ListOSPolicyAssignmentsRequest(parent=parent)
        )
    )

    if not assignments:
        print("  OSPolicyAssignment が見つかりませんでした")
        return

    for assignment in assignments:
        short_name = assignment.name.split("/")[-1]
        print(f"  ID             : {short_name}")
        print(f"  ロールアウト状態: {assignment.rollout_state.name}")
        print(f"  リソース名     : {assignment.name}")
        print()


def delete_assignment(zone: str, assignment_id: str) -> None:
    """指定 ID の OSPolicyAssignment を削除する。"""
    project_id = _get_project_id()
    client = osconfig_v1.OsConfigZonalServiceClient(
        credentials=_get_credentials(),
        transport="rest",
    )

    name = f"projects/{project_id}/locations/{zone}/osPolicyAssignments/{assignment_id}"

    print(f"[OS Config] OSPolicyAssignment を削除します: {assignment_id}")

    operation = client.delete_os_policy_assignment(
        request=osconfig_v1.DeleteOSPolicyAssignmentRequest(name=name)
    )
    print("  削除中... (LRO 完了まで待機)")
    operation.result()

    print(f"  削除完了: {assignment_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="OS Config を使って GCE インスタンスにコマンドを送信する"
    )

    parser.add_argument(
        "--zone",
        default=os.environ.get("GOOGLE_CLOUD_ZONE", "asia-northeast1-a"),
        help="ゾーン名 (デフォルト: 環境変数 GOOGLE_CLOUD_ZONE または asia-northeast1-a)",
    )
    parser.add_argument(
        "--command",
        default=None,
        help="GCE インスタンスで実行するシェルコマンド",
    )
    parser.add_argument(
        "--assignment-id",
        default=None,
        help="OSPolicyAssignment の ID (省略時は自動生成)",
    )
    parser.add_argument(
        "--label-key",
        default=None,
        help="インスタンスフィルター用ラベルキー (例: env)",
    )
    parser.add_argument(
        "--label-value",
        default=None,
        help="インスタンスフィルター用ラベル値 (例: dev)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="OSPolicyAssignment の一覧を表示する",
    )
    parser.add_argument(
        "--delete",
        metavar="ASSIGNMENT_ID",
        default=None,
        help="指定 ID の OSPolicyAssignment を削除する",
    )

    args = parser.parse_args()

    if args.list:
        list_assignments(zone=args.zone)
    elif args.delete:
        delete_assignment(zone=args.zone, assignment_id=args.delete)
    elif args.command:
        send_command(
            zone=args.zone,
            command=args.command,
            assignment_id=args.assignment_id,
            label_key=args.label_key,
            label_value=args.label_value,
        )
    else:
        parser.print_help()
        sys.exit(1)
