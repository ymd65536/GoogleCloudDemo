"""
google-cloud-python (google-cloud-compute) を使って
Compute Engine のインスタンスを作成するサンプル

インストール:
    pip install google-cloud-compute

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_ZONE=asia-northeast1-a   # 省略時は asia-northeast1-a
    export GOOGLE_CLOUD_INSTANCE=your-instance   # 作成するインスタンス名
    python create_compute_engine.py

    # オプションで直接指定も可能
    python create_compute_engine.py --zone asia-northeast1-a --instance my-vm --machine-type e2-micro
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import compute_v1

from gcp_auth import _get_credentials, _get_project_id


def create_instance(
    zone: str,
    instance_name: str,
    machine_type: str = "e2-micro",
    image_family: str = "debian-12",
    image_project: str = "debian-cloud",
    disk_size_gb: int = 10,
) -> None:
    """新しい Compute Engine インスタンスを作成する。

    Args:
        zone: 作成するゾーン (例: asia-northeast1-a)
        instance_name: 作成するインスタンス名
        machine_type: マシンタイプ (デフォルト: e2-micro)
        image_family: ブートディスクに使うイメージファミリー (デフォルト: debian-12)
        image_project: イメージが属するプロジェクト (デフォルト: debian-cloud)
        disk_size_gb: ブートディスクサイズ (GB、デフォルト: 10)
    """
    credentials = _get_credentials()
    project_id = _get_project_id()

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

    # ---- インスタンスリソースの組み立て ----
    instance = compute_v1.Instance(
        name=instance_name,
        machine_type=f"zones/{zone}/machineTypes/{machine_type}",
        disks=[boot_disk],
        network_interfaces=[network_interface],
    )

    # ---- API リクエストの実行 ----
    client = compute_v1.InstancesClient(credentials=credentials)
    request = compute_v1.InsertInstanceRequest(
        project=project_id,
        zone=zone,
        instance_resource=instance,
    )

    print(f"[google-cloud-python] インスタンスを作成します: {instance_name}")
    print(f"  プロジェクト  : {project_id}")
    print(f"  ゾーン        : {zone}")
    print(f"  マシンタイプ  : {machine_type}")
    print(f"  イメージ      : {image_project}/{image_family}")
    print(f"  ディスク容量  : {disk_size_gb} GB")

    # insert() は長時間オペレーションを返す
    operation = client.insert(request=request)

    # オペレーションが完了するまで待機
    operation.result()

    print(f"  作成完了: {instance_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute Engine インスタンスを作成する")
    parser.add_argument(
        "--zone",
        default=os.environ.get("GOOGLE_CLOUD_ZONE", "asia-northeast1-a"),
        help="ゾーン名 (デフォルト: 環境変数 GOOGLE_CLOUD_ZONE または asia-northeast1-a)",
    )
    parser.add_argument(
        "--instance",
        default=os.environ.get("GOOGLE_CLOUD_INSTANCE"),
        required=not os.environ.get("GOOGLE_CLOUD_INSTANCE"),
        help="インスタンス名 (デフォルト: 環境変数 GOOGLE_CLOUD_INSTANCE)",
    )
    parser.add_argument(
        "--machine-type",
        default="e2-micro",
        help="マシンタイプ (デフォルト: e2-micro)",
    )
    parser.add_argument(
        "--image-family",
        default="debian-12",
        help="ブートイメージファミリー (デフォルト: debian-12)",
    )
    parser.add_argument(
        "--image-project",
        default="debian-cloud",
        help="イメージのプロジェクト (デフォルト: debian-cloud)",
    )
    parser.add_argument(
        "--disk-size",
        type=int,
        default=10,
        help="ブートディスクサイズ GB (デフォルト: 10)",
    )
    args = parser.parse_args()

    create_instance(
        zone=args.zone,
        instance_name=args.instance,
        machine_type=args.machine_type,
        image_family=args.image_family,
        image_project=args.image_project,
        disk_size_gb=args.disk_size,
    )
