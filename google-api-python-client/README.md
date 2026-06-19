# google-api-python-client サンプル集

`google-api-python-client` および `gcloud` サブプロセスを使って Google Cloud を操作するスクリプト集です。

## 環境セットアップ

```bash
# プロジェクトルートで依存パッケージをインストール
cd /path/to/GoogleCloudDemo
uv sync

# 認証
gcloud auth application-default login

# プロジェクト・ゾーンを環境変数にセット
export GOOGLE_CLOUD_PROJECT=$(gcloud config get-value project)
export GOOGLE_CLOUD_ZONE=asia-northeast1-a
```

### SSL 証明書（社内プロキシ環境）

企業ネットワークで自己署名証明書を使っている場合は、CA バンドルのパスを設定してください。
スクリプトは環境変数が設定されていればそれを優先し、未設定時は `certifi` にフォールバックします。

```bash
export REQUESTS_CA_BUNDLE=/path/to/your-ca-bundle.pem
```

---

## スクリプト一覧

### artifact_registry.py

Artifact Registry のリポジトリ一覧を取得します。

```bash
export GOOGLE_CLOUD_LOCATION=asia-northeast1
.venv/bin/python artifact_registry.py
```

---

### compute_engine.py

Compute Engine のインスタンス一覧とステータスを取得します。

```bash
.venv/bin/python compute_engine.py
```

---

### start_compute_engine.py

指定した Compute Engine インスタンスを起動します。

```bash
export GOOGLE_CLOUD_INSTANCE=your-instance-name
.venv/bin/python start_compute_engine.py
```

---

### send_command.py

OS Config (OSPolicyAssignment + ExecResource) を使って、ラベル `managed-by=osconfig` のインスタンスにコマンドを送信し、Cloud Logging に実行履歴を記録します。

```bash
# デフォルト: /tmp/osconfig_result.txt を作成
.venv/bin/python send_command.py

# コマンドを指定
.venv/bin/python send_command.py --command "df -h"

# ゾーン・Assignment ID を指定
.venv/bin/python send_command.py --zone asia-northeast1-b --assignment-id my-cmd-01
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--zone` | ゾーン名 | `GOOGLE_CLOUD_ZONE` または `asia-northeast1-a` |
| `--command` | 実行するシェルコマンド | `echo "..." > /tmp/osconfig_result.txt` |
| `--assignment-id` | OSPolicyAssignment の ID | 自動生成 |
| `--label-key` | 対象ラベルキー | `managed-by` |
| `--label-value` | 対象ラベル値 | `osconfig` |

> **注意:** Assignment は自動削除されません。不要になったら削除してください。
> ```bash
> gcloud compute os-config os-policy-assignments delete <assignment-id> --location=<zone>
> ```

---

### gc-compute-run-task.py

OS Config (OSPolicyAssignment) でコマンドをインスタンスに送信します。
ラベル指定またはインスタンスID指定が可能です。

```bash
# ラベルで指定（デフォルト: managed-by=osconfig）
.venv/bin/python gc-compute-run-task.py --command "df -h"

# インスタンスID で指定（名前または数値ID）
.venv/bin/python gc-compute-run-task.py --instance-id {インスタンスID}

# ラベルを明示指定
.venv/bin/python gc-compute-run-task.py --label-key env --label-value prod
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--zone` | ゾーン名 | `asia-northeast1-a` |
| `--command` | 実行するシェルコマンド | `df -h` |
| `--label-key` | 対象ラベルキー | `managed-by` |
| `--label-value` | 対象ラベル値 | `osconfig` |
| `--instance-id` | インスタンス名または数値ID（ラベルより優先） | なし |

---

### run_command.py

OS Config でコマンドを送信し、実行結果をターミナルに表示します。
**Assignment は完了後に自動削除**されます。Cloud Logging への書き込みはありません。

インスタンスID指定時は Compute Engine API で一時ラベルを自動付与・削除します。

```bash
# インスタンス名で指定
.venv/bin/python run_command.py --instance-id {インスタンスID}

# 数値IDで指定
.venv/bin/python run_command.py --instance-id {インスタンスID}

# ラベルで指定
.venv/bin/python run_command.py --label managed-by=osconfig

# コマンドを変えて実行
.venv/bin/python run_command.py --instance-id {インスタンスID} --command "free -h"
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--zone` | ゾーン名 | `asia-northeast1-a` |
| `--command` | 実行するシェルコマンド | `df -h` |
| `--instance-id` | インスタンス名または数値ID（`--label` と排他必須） | — |
| `--label` | 対象ラベル `KEY=VALUE` 形式（`--instance-id` と排他必須） | — |

#### 実行結果の表示について

OS Config の `osPolicyAssignmentReports.enforcementOutput` (Base64) をデコードして表示します。
レポート反映まで最大 180 秒待機します。

---

### run_command_gcloud.py

`run_command.py` と同じ機能を **`gcloud` サブプロセスのみ**で実装したバージョンです。
`google-api-python-client` を使わないため、SSL 証明書の問題が発生しにくい環境に適しています。

```bash
# インスタンスID で指定
.venv/bin/python run_command_gcloud.py --instance-id {インスタンスID}

# 数値IDで指定
.venv/bin/python run_command_gcloud.py --instance-id {インスタンスID}

# ラベルで指定
.venv/bin/python run_command_gcloud.py --label managed-by=osconfig
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--zone` | ゾーン名 | `asia-northeast1-a` |
| `--command` | 実行するシェルコマンド | `df -h` |
| `--instance-id` | インスタンス名または数値ID（`--label` と排他必須） | — |
| `--label` | 対象ラベル `KEY=VALUE` 形式（`--instance-id` と排他必須） | — |

---

### iap_ssh.py

Compute Engine API でインスタンス情報を解決し、IAP (Identity-Aware Proxy) 経由で SSH 接続します。

```bash
# インタラクティブシェルを開く
.venv/bin/python iap_ssh.py --instance-id {インスタンスID}

# 数値IDでも可
.venv/bin/python iap_ssh.py --instance-id {インスタンスID}

# コマンドを実行して結果を表示
.venv/bin/python iap_ssh.py --instance-id {インスタンスID} --command "df -h"

# ゾーン指定で高速化（未指定時は全ゾーン検索）
.venv/bin/python iap_ssh.py --instance-id {インスタンスID} --zone asia-northeast1-a --command "free -h"

# SSH オプション追加
.venv/bin/python iap_ssh.py --instance-id {インスタンスID} --ssh-flag="-q"
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--instance-id` | インスタンス名または数値ID（必須） | — |
| `--zone` | ゾーン名（省略時は自動検索） | `GOOGLE_CLOUD_ZONE` |
| `--project` | GCP プロジェクトID | `GOOGLE_CLOUD_PROJECT` |
| `--command` | リモートで実行するコマンド（省略時はインタラクティブ） | なし |
| `--user` | SSH ユーザー名 | gcloud のデフォルト |
| `--port` | SSH ポート番号 | `22` |
| `--ssh-flag` | 追加の SSH フラグ（複数指定可） | なし |

#### IAP SSH の前提条件

1. ファイアウォールで IAP のソースレンジ `35.235.240.0/20` からの TCP:22 を許可
   ```bash
   gcloud compute firewall-rules create allow-iap-ssh \
     --allow=tcp:22 \
     --source-ranges=35.235.240.0/20
   ```
2. 接続ユーザーに `roles/iap.tunnelResourceAccessor` 権限が必要

> **補足:** デフォルトネットワークの `default-allow-ssh` ルール（`0.0.0.0/0` から TCP:22 許可）が有効な場合も IAP は通りますが、セキュリティ上は IAP 専用ルールへの切り替えを推奨します。

---

## OS Config の仕組み

`send_command.py` / `run_command.py` / `gc-compute-run-task.py` はすべて OS Config の **OSPolicyAssignment + ExecResource** パターンを使用しています。

```
OSPolicyAssignment
└── OSPolicy (mode: ENFORCEMENT)
    └── ResourceGroup
        └── ExecResource
            ├── validate: exit 101  ← 常に enforce を実行させるためのダミー
            └── enforce:  <コマンド>
                          exit 100  ← OS Config に「適用完了」を伝える
```

### インスタンスID指定時の一時ラベル方式

OS Config の `instanceFilter` はラベルでしかフィルタリングできないため、インスタンスID指定時は以下のフローで処理します。

```
① Compute Engine API でインスタンスに一時ラベル付与
   (osconfig-tmp-target=<ランダム値>)
② そのラベルで OSPolicyAssignment を作成・実行
③ ロールアウト完了 → レポート取得
④ Assignment 削除 + 一時ラベル削除
```

---

## 必要な権限

| 操作 | 必要なロール |
|---|---|
| OSPolicyAssignment の作成・削除 | `roles/osconfig.osPolicyAssignmentAdmin` |
| インスタンスラベルの操作 | `roles/compute.instanceAdmin.v1` |
| Cloud Logging への書き込み | `roles/logging.logWriter` |
| IAP SSH | `roles/iap.tunnelResourceAccessor` |
| インスタンス情報の参照 | `roles/compute.viewer` |
