"""
google-cloud-python (google-cloud-compute) を使って
Compute Engine のインスタンスを停止するサンプル

インストール:
    pip install google-cloud-compute

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_ZONE=asia-northeast1-a      # 省略時は asia-northeast1-a
    export GOOGLE_CLOUD_INSTANCE=your-instance      # 停止するインスタンス名
    python stop_compute_engine.py

    # オプションで直接指定も可能
    python stop_compute_engine.py --zone asia-northeast1-a --instance my-vm
"""

import argparse
import os

from google.cloud import compute_v1

from gcp_auth import _get_credentials, _get_project_id


def stop_instance(zone: str, instance_name: str) -> None:
    """指定したインスタンスを停止する (RUNNING → TERMINATED)。"""
    client = compute_v1.InstancesClient(credentials=_get_credentials())
    project_id = _get_project_id()

    print(f"[google-cloud-python] インスタンスを停止します: {instance_name} ({zone})")

    # stop() は長時間オペレーションを返す
    operation = client.stop(
        project=project_id,
        zone=zone,
        instance=instance_name,
    )

    # オペレーションが完了するまで待機
    operation.result()

    print(f"  停止完了: {instance_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute Engine インスタンスを停止する")
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
    args = parser.parse_args()

    stop_instance(args.zone, args.instance)
