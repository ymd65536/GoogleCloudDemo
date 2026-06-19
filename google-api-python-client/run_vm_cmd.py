"""
OS Config API で既存 GCE VM にコマンドを実行する

SSH / WebSocket / gcloud 不要。
google-cloud-compute でインスタンス解決し、
google-cloud-osconfig で非対話コマンドを実行する。

前提条件:
  - VM に OS Config エージェントが稼働中であること
  - roles/osconfig.osPolicyAssignmentAdmin (コマンド実行)
  - roles/compute.instanceAdmin.v1 (ラベル付与)

使い方:
    python run_vm_cmd.py --instance-id my-instance --command "df -h"
    python run_vm_cmd.py --instance-id {インスタンスID} --command "uptime"
"""

import argparse
import datetime
import os
import sys
import time
import uuid

from google.cloud import compute_v1, osconfig_v1

# 企業プロキシ CA バンドル対応
_CA = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
if _CA:
    os.environ.setdefault("SSL_CERT_FILE", _CA)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _CA)


# ─── インスタンス解決 ─────────────────────────────────────────────────────────

def _resolve_instance(project_id: str, name_or_id: str, zone: str | None) -> tuple[str, str]:
    instances = compute_v1.InstancesClient()
    zones = compute_v1.ZonesClient()

    # zone 未指定時は環境変数を優先して使用
    if not zone:
        zone = os.environ.get("GOOGLE_CLOUD_ZONE")

    if name_or_id.isdigit():
        print(f"  数値ID {name_or_id} を解決中...", file=sys.stderr)
        zone_list = [zone] if zone else [z.name for z in zones.list(project=project_id)]
        for z in zone_list:
            for inst in instances.list(project=project_id, zone=z):
                if str(inst.id) == name_or_id:
                    print(f"  → {inst.name} / {z}", file=sys.stderr)
                    return inst.name, z
        raise ValueError(f"数値ID {name_or_id} のインスタンスが見つかりません")

    if zone:
        return name_or_id, zone

    print(f"  '{name_or_id}' のゾーンを検索中...", file=sys.stderr)
    for z in [z.name for z in zones.list(project=project_id)]:
        try:
            instances.get(project=project_id, zone=z, instance=name_or_id)
            print(f"  → ゾーン: {z}", file=sys.stderr)
            return name_or_id, z
        except Exception:
            continue
    raise ValueError(f"インスタンス '{name_or_id}' が見つかりません")


# ─── ラベル操作 ───────────────────────────────────────────────────────────────

def _set_label(project_id: str, zone: str, instance: str, key: str, value: str | None):
    """ラベルを追加 (value=None で削除)。compute_v1 の ExtendedOperation で完了まで待機。"""
    client = compute_v1.InstancesClient()
    inst = client.get(project=project_id, zone=zone, instance=instance)
    labels = {k: v for k, v in (inst.labels or {}).items() if k != key}
    if value is not None:
        labels[key] = value
    client.set_labels(
        project=project_id, zone=zone, instance=instance,
        instances_set_labels_request_resource=compute_v1.InstancesSetLabelsRequest(
            label_fingerprint=inst.label_fingerprint,
            labels=labels,
        ),
    ).result()


# ─── コマンド実行 ─────────────────────────────────────────────────────────────

def run_command(project_id: str, zone: str, instance: str, command: str) -> None:
    label_key = "run-cmd-target"
    label_value = f"cmd-{uuid.uuid4().hex[:8]}"
    assignment_id = f"run-cmd-{uuid.uuid4().hex[:8]}"
    parent = f"projects/{project_id}/locations/{zone}"
    # gRPC は instances/- ワイルドカードを受け付けないため REST を使用
    osconfig = osconfig_v1.OsConfigZonalServiceClient(transport="rest")

    print(f"  ラベル付与: {label_key}={label_value}", file=sys.stderr)
    _set_label(project_id, zone, instance, label_key, label_value)

    try:
        # OS Policy Assignment: validate=常にOK、enforce=実行したいコマンド
        assignment = osconfig_v1.OSPolicyAssignment(
            os_policies=[osconfig_v1.OSPolicy(
                id="run-cmd",
                mode=osconfig_v1.OSPolicy.Mode.ENFORCEMENT,
                resource_groups=[osconfig_v1.OSPolicy.ResourceGroup(
                    resources=[osconfig_v1.OSPolicy.Resource(
                        id="exec",
                        exec_=osconfig_v1.OSPolicy.Resource.ExecResource(
                            validate=osconfig_v1.OSPolicy.Resource.ExecResource.Exec(
                                script="exit 101",  # 101=not compliant → enforce を必ず実行
                                interpreter=osconfig_v1.OSPolicy.Resource.ExecResource.Exec.Interpreter.SHELL,
                            ),
                            enforce=osconfig_v1.OSPolicy.Resource.ExecResource.Exec(
                                script=f"{command}\nexit 100",  # 100=enforcement applied
                                interpreter=osconfig_v1.OSPolicy.Resource.ExecResource.Exec.Interpreter.SHELL,
                            ),
                        ),
                    )],
                )],
            )],
            instance_filter=osconfig_v1.OSPolicyAssignment.InstanceFilter(
                inclusion_labels=[osconfig_v1.OSPolicyAssignment.LabelSet(
                    labels={label_key: label_value}
                )]
            ),
            rollout=osconfig_v1.OSPolicyAssignment.Rollout(
                disruption_budget=osconfig_v1.FixedOrPercent(percent=100),
                min_wait_duration=datetime.timedelta(seconds=0),
            ),
        )

        print(f"  Assignment 作成: {assignment_id}", file=sys.stderr)
        # create の LRO はロールアウト完了まで終わらないため .result() を待たない。
        # エージェントが Assignment を拾ってレポートを返すまで直接ポーリングする。
        osconfig.create_os_policy_assignment(
            parent=parent,
            os_policy_assignment=assignment,
            os_policy_assignment_id=assignment_id,
        )

        # OS Config エージェントが Assignment を検出してコマンドを実行するまで待機
        # instances/- ワイルドカードの代わりにインスタンス名を直接指定
        # API 制約: instance か assignment のどちらか一方は "-" (ワイルドカード) にする必要がある
        report_parent = f"{parent}/instances/-/osPolicyAssignments/{assignment_id}"
        for i in range(6):  # 最大 1 分
            time.sleep(10)
            print(f"  待機中... ({(i + 1) * 10}s)", file=sys.stderr, end="\r")
            for report in osconfig.list_os_policy_assignment_reports(parent=report_parent):
                # 対象インスタンスのレポートのみを処理
                if f"/instances/{instance}/" not in report.name:
                    continue
                for policy in report.os_policy_compliance_states:
                    for res in policy.os_policy_resource_compliances:
                        output = res.exec_resource_output.enforcement_output
                        if output:
                            print(file=sys.stderr)
                            print("--- 実行結果 ---")
                            print(output.decode(errors="replace").rstrip())
                            print("----------------")
                            return

        print(file=sys.stderr)
        print("  タイムアウト: レポートが返りませんでした", file=sys.stderr)
        print("  OS Config エージェントが稼働中か確認してください:", file=sys.stderr)
        print("    sudo systemctl status google-osconfig-agent", file=sys.stderr)
        print("  Cloud Logging フィルタ:", file=sys.stderr)
        print(f'    resource.type="gce_instance" jsonPayload.localName="{assignment_id}"', file=sys.stderr)

    finally:
        # 後片付け: キャンセル → ロールアウト完了まで待機 → 削除
        assignment_name = f"{parent}/osPolicyAssignments/{assignment_id}"
        try:
            osconfig.cancel_os_policy_assignment_rollout(name=assignment_name)
        except Exception:
            pass  # すでに完了済みの場合は無視
        # ロールアウトが CANCELLED に遷移するまでポーリング
        for _ in range(12):
            time.sleep(5)
            try:
                a = osconfig.get_os_policy_assignment(name=assignment_name)
                if not a.rollout_state == osconfig_v1.OSPolicyAssignment.RolloutState.IN_PROGRESS:
                    break
            except Exception:
                break
        try:
            osconfig.delete_os_policy_assignment(name=assignment_name)
            print("  Assignment を削除しました", file=sys.stderr)
        except Exception as e:
            print(f"  警告: Assignment 削除失敗 ({e})", file=sys.stderr)
        _set_label(project_id, zone, instance, label_key, None)
        print("  ラベルを削除しました", file=sys.stderr)


# ─── エントリーポイント ───────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="OS Config API で GCE VM にコマンドを実行 (SSH不要)")
    p.add_argument("--instance-id", required=True, help="インスタンス名または数値ID")
    p.add_argument("--command", required=True, help="実行するコマンド (例: 'df -h')")
    p.add_argument("--zone", default=os.environ.get("GOOGLE_CLOUD_ZONE"),
                   help="ゾーン名 (省略時は自動検索、GOOGLE_CLOUD_ZONE も利用可)")
    p.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                   help="GCP プロジェクトID (省略時は GOOGLE_CLOUD_PROJECT)")
    args = p.parse_args()

    if not args.project:
        print("エラー: --project または GOOGLE_CLOUD_PROJECT を設定してください", file=sys.stderr)
        sys.exit(1)

    print(f"  プロジェクト: {args.project}", file=sys.stderr)
    try:
        inst, zone = _resolve_instance(args.project, args.instance_id, args.zone)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  インスタンス: {inst} / {zone}", file=sys.stderr)
    run_command(args.project, zone, inst, args.command)


if __name__ == "__main__":
    main()
