"""CLIで OS Config の patchJobs.execute を実行する（ADC + google-api-python-client）

目的:
    - IAP SSH ではなく、OS Config の patchJobs.execute を API で実行する
    - 認証は ADC（application-default login）を利用する

使い方例:
    .venv/bin/python3 google-api-python-client/os-config-cli.py \
        --patch-job-id my-patch-job \
        --all \
        --apt "{"'"'packageName'"'":'"'nginx'"'}"

前提:
    - gcloud auth application-default login 済み
    - OS Config の patchJobs.execute に必要な権限
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Optional

import certifi

# 環境変数が既に設定されている場合はそれを優先し、未設定時のみ certifi にフォールバック
_CA_BUNDLE = (
    os.environ.get("REQUESTS_CA_BUNDLE")
    or os.environ.get("SSL_CERT_FILE")
    or certifi.where()
)
os.environ["SSL_CERT_FILE"] = _CA_BUNDLE
os.environ["REQUESTS_CA_BUNDLE"] = _CA_BUNDLE

from google.auth import default as google_auth_default

try:
    # 同階層の os-config.py をモジュールとして読み込む
    from os_config import action  # type: ignore
except ModuleNotFoundError:
    import importlib.util
    from pathlib import Path

    here = Path(__file__).resolve().parent
    target = here / "os-config.py"
    spec = importlib.util.spec_from_file_location("os_config", target)
    if spec is None or spec.loader is None:
        raise ImportError(f"os-config.py を読み込めません: {target}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    action = module.action


def _get_project(arg: Optional[str]) -> str:
    if arg:
        return arg
    pid = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if pid:
        return pid
    # ADC から project_id を取得
    _, project_id = google_auth_default()
    if not project_id:
        raise ValueError(
            "プロジェクトIDが取得できません。"
            "GOOGLE_CLOUD_PROJECT を設定するか --project を指定してください。"
        )
    return project_id


def _resolve_instance(name_or_id: str, project: str, zone: Optional[str]) -> tuple[str, str]:
    """インスタンス名または数値IDからインスタンス名とゾーンを返す。

    zone が指定されている場合は、数値IDでもその zone に限定して解決する。
    """
    # iap_run.py と同じ方針で gcloud を使って解決する（APIだけでやると実装が増えるため）。
    import subprocess

    def _gcloud(*args: str) -> subprocess.CompletedProcess[str]:
        cmd = ["gcloud", *args]
        return subprocess.run(cmd, capture_output=True, text=True, check=True)

    if not name_or_id.isdigit():
        if zone:
            return name_or_id, zone
        r = _gcloud(
            "compute",
            "instances",
            "list",
            f"--filter=name={name_or_id}",
            "--format=value(name,zone)",
            f"--project={project}",
        )
        line = r.stdout.strip()
        if not line:
            raise ValueError(f"インスタンス '{name_or_id}' が見つかりません")
        name, z = line.split("\t")
        return name, z

    # 数値ID指定
    filter_arg = f"--filter=id={name_or_id}"
    args = [
        "compute",
        "instances",
        "list",
        filter_arg,
        "--format=value(name,zone)",
        f"--project={project}",
    ]
    if zone:
        args.append(f"--zones={zone}")
    r = _gcloud(*args)
    line = r.stdout.strip()
    if not line:
        raise ValueError(f"数値ID {name_or_id} のインスタンスが見つかりません")
    name, z = line.split("\t")
    return name, z


def main() -> None:
    p = argparse.ArgumentParser(description="OS Config patchJobs.execute を ADC 経由で実行")
    p.add_argument("--patch-job-id", required=True, help="patch job のID")
    p.add_argument("--project", default=None, help="GCP プロジェクトID（省略時は GOOGLE_CLOUD_PROJECT / ADC）")

    # instanceFilter
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="全インスタンスに適用")
    g.add_argument("--zones", default=None, help="適用対象ゾーン（カンマ区切り）")
    g.add_argument("--instance-name-prefixes", default=None, help="適用対象インスタンス名プレフィックス（カンマ区切り）")

    # patchConfig（最小例として apt/yum/zypper/windowsUpdate のどれかをJSONで渡す）
    p.add_argument("--apt", default=None, help="AptSettings を JSON 文字列で指定")
    p.add_argument("--yum", default=None, help="YumSettings を JSON 文字列で指定")
    p.add_argument("--zypper", default=None, help="ZypperSettings を JSON 文字列で指定")
    p.add_argument("--windows-update", default=None, help="WindowsUpdateSettings を JSON 文字列で指定")

    args = p.parse_args()

    project = _get_project(args.project)
    # ADC credentials を取得
    credentials, _ = google_auth_default()

    # instanceFilter
    if args.all:
        instance_filter: dict[str, Any] = {"all": True}
    else:
        instance_filter = {}
        if args.zones:
            instance_filter["zones"] = [z.strip() for z in args.zones.split(",") if z.strip()]
        if args.instance_name_prefixes:
            instance_filter["instanceNamePrefixes"] = [
                s.strip() for s in args.instance_name_prefixes.split(",") if s.strip()
            ]
        if not instance_filter:
            raise ValueError("--all もしくは --zones/--instance-name-prefixes の指定が必要です")

    # patchConfig
    patch_config: dict[str, Any] = {}
    patch_config_key = None
    patch_config_value = None
    for key, raw in [
        ("apt", args.apt),
        ("yum", args.yum),
        ("zypper", args.zypper),
        ("windowsUpdate", args.windows_update),
    ]:
        if raw is not None:
            if patch_config_key is not None:
                raise ValueError("patchConfig は --apt/--yum/--zypper/--windows-update のいずれか1つだけ指定してください")
            patch_config_key = key
            patch_config_value = json.loads(raw)

    if patch_config_key is None:
        raise ValueError("patchConfig を指定してください（--apt/--yum/--zypper/--windows-update のいずれか）")
    patch_config[patch_config_key] = patch_config_value

    parameters = {
        "project_id": project,
        "patch_job_id": args.patch_job_id,
        "instance_filter": instance_filter,
        "patch_config": patch_config,
    }

    result = action(parameters, credentials)
    print(result)


if __name__ == "__main__":
    main()
