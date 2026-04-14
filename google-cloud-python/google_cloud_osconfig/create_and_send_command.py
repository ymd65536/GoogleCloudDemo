"""
GCE インスタンスを作成し、OS Config でコマンドを送信するサンプル

以下の手順を一括で実行します。
  1. ラベル付きの GCE インスタンスを作成する
  2. インスタンスが RUNNING になるまで待機する
  3. OS Config エージェントの起動を待機する
  4. OSPolicyAssignment を作成してコマンドを送信する

インストール:
    pip install google-cloud-compute google-cloud-os-config

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_ZONE=asia-northeast1-a  # 省略時は asia-northeast1-a

    # デフォルト (インスタンス名自動生成、コマンド: echo hello)
    python create_and_send_command.py

    # インスタンス名とコマンドを指定
    python create_and_send_command.py --instance my-vm --command "df -h"

必要な権限:
    - roles/compute.instanceAdmin.v1 (インスタンス作成)
    - roles/osconfig.osPolicyAssignmentAdmin (OSPolicyAssignment 作成・削除)

注意:
    Debian 12 には google-osconfig-agent がデフォルトでインストールされていますが、
    起動完了まで数分かかることがあります。
    本スクリプトでは --agent-wait-seconds で待機時間を調整できます。
"""

import argparse
import datetime
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import compute_v1, logging as gcp_logging, osconfig_v1
from google.protobuf import duration_pb2

from gcp_auth import _get_credentials, _get_project_id, _get_project_number

# Cloud Logging のログ名
_LOG_NAME = "osconfig-command-history"


def _get_logger():
    """Cloud Logging のロガーを返す。"""
    project_id = _get_project_id()
    client = gcp_logging.Client(
        project=project_id,
        credentials=_get_credentials(),
        _use_grpc=False,
    )
    return client.logger(_LOG_NAME)

# OS Config エージェントを有効化するメタデータキー
_OSCONFIG_ENABLE_KEY = "enable-osconfig"
_OSCONFIG_ENABLE_VALUE = "TRUE"

# インスタンスを OS Config のフィルタリング対象として識別するラベル
_MANAGED_LABEL_KEY = "managed-by"
_MANAGED_LABEL_VALUE = "osconfig"


# ---------------------------------------------------------------------------
# GCE インスタンス作成
# ---------------------------------------------------------------------------

def create_instance(
    zone: str,
    instance_name: str,
    machine_type: str = "e2-micro",
    image_family: str = "debian-12",
    image_project: str = "debian-cloud",
    disk_size_gb: int = 10,
    service_account_email: str | None = None,
) -> None:
    """OS Config エージェントを有効化したラベル付き GCE インスタンスを作成する。"""
    credentials = _get_credentials()
    project_id = _get_project_id()

    # サービスアカウント未指定の場合はデフォルト Compute SA を使用
    if service_account_email is None:
        project_number = _get_project_number()
        service_account_email = f"{project_number}-compute@developer.gserviceaccount.com"

    # ---- ブートディスクの設定 ----
    initialize_params = compute_v1.AttachedDiskInitializeParams(
        source_image=f"projects/{image_project}/global/images/family/{image_family}",
        disk_size_gb=disk_size_gb,
        disk_type=f"zones/{zone}/diskTypes/pd-balanced",
    )
    boot_disk = compute_v1.AttachedDisk(
        boot=True,
        auto_delete=True,
        initialize_params=initialize_params,
    )

    # ---- ネットワークインターフェースの設定 (外部IPあり) ----
    access_config = compute_v1.AccessConfig(
        name="External NAT",
        network_tier="PREMIUM",
    )
    network_interface = compute_v1.NetworkInterface(
        name="global/networks/default",
        access_configs=[access_config],
    )

    # ---- メタデータ: OS Config エージェントを有効化 ----
    metadata = compute_v1.Metadata(
        items=[
            compute_v1.Items(
                key=_OSCONFIG_ENABLE_KEY,
                value=_OSCONFIG_ENABLE_VALUE,
            )
        ]
    )

    # ---- サービスアカウントの設定 ----
    service_account = compute_v1.ServiceAccount(
        email=service_account_email,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )

    # ---- インスタンスリソースの組み立て ----
    instance = compute_v1.Instance(
        name=instance_name,
        machine_type=f"zones/{zone}/machineTypes/{machine_type}",
        disks=[boot_disk],
        network_interfaces=[network_interface],
        metadata=metadata,
        labels={_MANAGED_LABEL_KEY: _MANAGED_LABEL_VALUE},
        service_accounts=[service_account],
    )

    client = compute_v1.InstancesClient(credentials=credentials)
    request = compute_v1.InsertInstanceRequest(
        project=project_id,
        zone=zone,
        instance_resource=instance,
    )

    print("[STEP 1] GCE インスタンスを作成します")
    print(f"  プロジェクト  : {project_id}")
    print(f"  ゾーン        : {zone}")
    print(f"  インスタンス名: {instance_name}")
    print(f"  マシンタイプ  : {machine_type}")
    print(f"  イメージ      : {image_project}/{image_family}")
    print(f"  ラベル        : {_MANAGED_LABEL_KEY}={_MANAGED_LABEL_VALUE}")
    print(f"  OS Config     : 有効 ({_OSCONFIG_ENABLE_KEY}={_OSCONFIG_ENABLE_VALUE})")
    print(f"  サービスアカウント: {service_account_email}")

    operation = client.insert(request=request)
    operation.result()

    print(f"  作成完了: {instance_name}")
    print()


def wait_for_running(zone: str, instance_name: str, timeout: int = 300) -> None:
    """インスタンスが RUNNING 状態になるまでポーリングする。"""
    credentials = _get_credentials()
    project_id = _get_project_id()
    client = compute_v1.InstancesClient(credentials=credentials)

    print("[STEP 2] インスタンスの RUNNING 状態を待機します")
    deadline = time.time() + timeout
    while time.time() < deadline:
        instance = client.get(project=project_id, zone=zone, instance=instance_name)
        status = instance.status
        print(f"  状態: {status}")
        if status == "RUNNING":
            print("  RUNNING を確認しました")
            print()
            return
        time.sleep(10)

    raise TimeoutError(
        f"インスタンス {instance_name} が {timeout} 秒以内に RUNNING になりませんでした"
    )


# ---------------------------------------------------------------------------
# OS Config: コマンド送信
# ---------------------------------------------------------------------------

def _build_exec_resource(command: str) -> osconfig_v1.OSPolicy.Resource:
    """シェルコマンドを実行する ExecResource を作成する。"""
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


def send_command(zone: str, command: str, assignment_id: str) -> osconfig_v1.OSPolicyAssignment:
    """ラベル managed-by=osconfig のインスタンスにコマンドを送信する。"""
    project_id = _get_project_id()
    client = osconfig_v1.OsConfigZonalServiceClient(
        credentials=_get_credentials(),
        transport="rest",
    )

    parent = f"projects/{project_id}/locations/{zone}"

    resource_group = osconfig_v1.OSPolicy.ResourceGroup(
        resources=[_build_exec_resource(command)]
    )
    os_policy = osconfig_v1.OSPolicy(
        id="exec-command-policy",
        mode=osconfig_v1.OSPolicy.Mode.ENFORCEMENT,
        resource_groups=[resource_group],
    )

    label_set = osconfig_v1.OSPolicyAssignment.LabelSet(
        labels={_MANAGED_LABEL_KEY: _MANAGED_LABEL_VALUE}
    )
    instance_filter = osconfig_v1.OSPolicyAssignment.InstanceFilter(
        inclusion_labels=[label_set]
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

    print("[STEP 4] OSPolicyAssignment を作成してコマンドを送信します")
    print(f"  Assignment ID: {assignment_id}")
    print(f"  コマンド     : {command}")
    print(f"  対象ラベル   : {_MANAGED_LABEL_KEY}={_MANAGED_LABEL_VALUE}")

    operation = client.create_os_policy_assignment(
        request=osconfig_v1.CreateOSPolicyAssignmentRequest(
            parent=parent,
            os_policy_assignment=os_policy_assignment,
            os_policy_assignment_id=assignment_id,
        )
    )
    print("  作成中... (LRO 完了まで待機)")
    result = operation.result()

    print(f"  送信完了: {result.name}")
    print(f"  ロールアウト状態: {result.rollout_state.name}")
    print()

    # Cloud Logging にコマンド送信履歴を記録
    logger = _get_logger()
    logger.log_struct(
        {
            "assignment_id": assignment_id,
            "command": command,
            "zone": zone,
            "rollout_state": result.rollout_state.name,
            "resource_name": result.name,
            "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
        severity="INFO",
    )
    print(f"  Cloud Logging に記録しました (ログ名: {_LOG_NAME})")
    print()

    return result


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="GCE インスタンスを作成して OS Config でコマンドを送信する"
    )
    parser.add_argument(
        "--zone",
        default=os.environ.get("GOOGLE_CLOUD_ZONE", "asia-northeast1-a"),
        help="ゾーン名 (デフォルト: 環境変数 GOOGLE_CLOUD_ZONE または asia-northeast1-a)",
    )
    parser.add_argument(
        "--instance",
        default=os.environ.get("GOOGLE_CLOUD_INSTANCE", f"osconfig-demo-{uuid.uuid4().hex[:6]}"),
        help="作成するインスタンス名 (省略時は自動生成)",
    )
    parser.add_argument(
        "--machine-type",
        default="e2-micro",
        help="マシンタイプ (デフォルト: e2-micro)",
    )
    parser.add_argument(
        "--command",
        default="echo hello from OS Config",
        help="GCE インスタンスで実行するコマンド (デフォルト: echo hello from OS Config)",
    )
    parser.add_argument(
        "--agent-wait-seconds",
        type=int,
        default=90,
        help="OS Config エージェント起動待機秒数 (デフォルト: 90)",
    )
    args = parser.parse_args()

    # Step 1: インスタンス作成
    create_instance(
        zone=args.zone,
        instance_name=args.instance,
        machine_type=args.machine_type,
    )

    # Step 2: RUNNING 待機
    wait_for_running(zone=args.zone, instance_name=args.instance)

    # Step 3: OS Config エージェント起動待機
    print(f"[STEP 3] OS Config エージェントの起動を {args.agent_wait_seconds} 秒待機します")
    for remaining in range(args.agent_wait_seconds, 0, -10):
        print(f"  残り {remaining} 秒...")
        time.sleep(min(10, remaining))
    print("  待機完了")
    print()

    # Step 4: コマンド送信
    assignment_id = f"cmd-{uuid.uuid4().hex[:8]}"
    send_command(
        zone=args.zone,
        command=args.command,
        assignment_id=assignment_id,
    )

    print("=" * 60)
    print("完了サマリー")
    print(f"  インスタンス名  : {args.instance}")
    print(f"  ゾーン          : {args.zone}")
    print(f"  送信コマンド    : {args.command}")
    print(f"  Assignment ID   : {assignment_id}")
    print()
    print("OSPolicyAssignment は不要になったら削除してください:")
    print(f"  python os_policy_assignment.py --delete {assignment_id} --zone {args.zone}")
