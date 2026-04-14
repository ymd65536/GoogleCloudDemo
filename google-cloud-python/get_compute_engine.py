"""
google-cloud-python (google-cloud-compute) を使って
プロジェクト全体の Compute Engine インスタンス一覧を取得するサンプル。
AggregatedList を使用して全ゾーンのインスタンスを一括取得する。

インストール:
    pip install google-cloud-compute

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    python get_compute_engine.py
"""

from google.cloud import compute_v1
from gcp_auth import _get_credentials, _get_project_id


def list_all_instances() -> None:
    """全ゾーンのインスタンスを集約リストで取得して表示する。"""
    client = compute_v1.InstancesClient(credentials=_get_credentials())
    request = compute_v1.AggregatedListInstancesRequest(project=_get_project_id())

    print("[google-cloud-python] Compute Engine インスタンス一覧 (全ゾーン)")
    print("-" * 60)

    found = False
    # aggregated_list はゾーンをキーとする辞書のページネーター
    for zone, response in client.aggregated_list(request=request):
        if response.instances:
            for instance in response.instances:
                found = True
                print(f"  名前        : {instance.name}")
                print(f"  状態        : {instance.status}")
                print(f"  マシンタイプ: {instance.machine_type.split('/')[-1]}")
                print(f"  ゾーン      : {zone.removeprefix('zones/')}")
                print()

    if not found:
        print("  インスタンスが見つかりませんでした")


if __name__ == "__main__":
    list_all_instances()
