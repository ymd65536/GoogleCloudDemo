"""
google-cloud-python (google-cloud-compute) を使って
Compute Engine のインスタンスを再起動するサンプル

再起動方式:
    --hard  ハードリセット (reset): 強制的に即時リセット (デフォルト)
    --soft  ソフトリスタート (stop → start): グレースフルシャットダウン後に起動

インストール:
    pip install google-cloud-compute

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_ZONE=asia-northeast1-a      # 省略時は asia-northeast1-a
    export GOOGLE_CLOUD_INSTANCE=your-instance      # 再起動するインスタンス名
    python restart_compute_engine.py

    # ソフトリスタート (stop → start) の場合
    python restart_compute_engine.py --instance my-vm --soft
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import compute_v1

from gcp_auth import _get_credentials, _get_project_id


def hard_reset_instance(zone: str, instance_name: str) -> None:
    """ハードリセット: 実行中のインスタンスを即時リセットする (RUNNING のまま再起動)。"""
    client = compute_v1.InstancesClient(credentials=_get_credentials())
    project_id = _get_project_id()

    print(f"[google-cloud-python] インスタンスをハードリセットします: {instance_name} ({zone})")

    # reset() は長時間オペレーションを返す
    operation = client.reset(
        project=project_id,
        zone=zone,
        instance=instance_name,
    )

    operation.result()
    print(f"  ハードリセット完了: {instance_name}")


def soft_restart_instance(zone: str, instance_name: str) -> None:
    """ソフトリスタート: グレースフルに停止してから起動する (RUNNING → TERMINATED → RUNNING)。"""
    client = compute_v1.InstancesClient(credentials=_get_credentials())
    project_id = _get_project_id()

    print(f"[google-cloud-python] インスタンスを停止します: {instance_name} ({zone})")
    client.stop(
        project=project_id,
        zone=zone,
        instance=instance_name,
    ).result()
    print(f"  停止完了: {instance_name}")

    print(f"  インスタンスを起動します: {instance_name} ({zone})")
    client.start(
        project=project_id,
        zone=zone,
        instance=instance_name,
    ).result()
    print(f"  起動完了: {instance_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute Engine インスタンスを再起動する")
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

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--hard",
        action="store_true",
        default=True,
        help="ハードリセット (デフォルト): reset API を使って即時リセット",
    )
    mode.add_argument(
        "--soft",
        action="store_true",
        default=False,
        help="ソフトリスタート: stop → start でグレースフルに再起動",
    )
    args = parser.parse_args()

    if args.soft:
        soft_restart_instance(args.zone, args.instance)
    else:
        hard_reset_instance(args.zone, args.instance)
