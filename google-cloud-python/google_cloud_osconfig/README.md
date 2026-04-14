# google_cloud_osconfig サンプル集

`google-cloud-os-config` ライブラリを使って GCE インスタンスにコマンドを送信するサンプルスクリプト集です。

OS Config の **OSPolicyAssignment** と **ExecResource** を組み合わせて、ゾーン内のインスタンスに任意のシェルコマンドを配布・実行できます。

## 前提条件

### 動作環境

- Python 3.12 以上
- [uv](https://docs.astral.sh/uv/)

### セットアップ

リポジトリルートで仮想環境を作成し、依存パッケージをインストールします。

```bash
# 仮想環境の作成と依存パッケージのインストール
uv sync

# 仮想環境を有効化
source .venv/bin/activate
```

`google-cloud-os-config` のみを個別に追加する場合:

```bash
uv add google-cloud-os-config
```

### 認証

[ADC (Application Default Credentials)](https://cloud.google.com/docs/authentication/application-default-credentials) を使用します。

```bash
gcloud auth application-default login
```

クォータプロジェクトの警告が出る場合は以下のコマンドを実行してください。

```bash
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

### GCE インスタンス側の準備

対象インスタンスに `google-osconfig-agent` が起動していること。

```bash
# Debian / Ubuntu
sudo systemctl status google-osconfig-agent

# エージェントが未インストールの場合
sudo apt-get install google-osconfig-agent
```

### 必要な IAM 権限

| 操作 | 必要なロール |
|---|---|
| インスタンスの作成 | `roles/compute.instanceAdmin.v1` |
| OSPolicyAssignment の作成・削除 | `roles/osconfig.osPolicyAssignmentAdmin` |
| OSPolicyAssignment の一覧表示 | `roles/osconfig.osPolicyAssignmentViewer` |

### 環境変数

| 環境変数 | 説明 | デフォルト |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | プロジェクトID | ADCから自動取得 |
| `GOOGLE_CLOUD_ZONE` | ターゲットゾーン | `asia-northeast1-a` |

---

## スクリプト一覧

| スクリプト | 説明 |
|---|---|
| `create_and_send_command.py` | GCE インスタンスを作成してコマンドを送信する (統合スクリプト) |
| `os_policy_assignment.py` | GCE インスタンスへのコマンド送信 / 一覧表示 / 削除 |

---

## create_and_send_command.py

GCE インスタンスの作成から OS Config によるコマンド送信までを一括で実行します。

### 実行フロー

```
STEP 1: GCE インスタンスを作成する
         ↓ ラベル managed-by=osconfig + メタデータ enable-osconfig=TRUE を付与
STEP 2: インスタンスが RUNNING になるまで待機する
STEP 3: OS Config エージェントの起動を待機する (デフォルト 90 秒)
STEP 4: OSPolicyAssignment を作成してコマンドを送信する
```

### 実行例

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_ZONE=asia-northeast1-a

# デフォルト設定で実行 (インスタンス名自動生成、コマンド: echo hello from OS Config)
python create_and_send_command.py

# インスタンス名とコマンドを指定
python create_and_send_command.py --instance my-vm --command "df -h"
```

### オプション一覧

| オプション | 説明 | デフォルト |
|---|---|---|
| `--zone` | ゾーン名 | 環境変数 `GOOGLE_CLOUD_ZONE` または `asia-northeast1-a` |
| `--instance` | 作成するインスタンス名 | 自動生成 (`osconfig-demo-<uuid>`) |
| `--machine-type` | マシンタイプ | `e2-micro` |
| `--command` | 実行するシェルコマンド | `echo hello from OS Config` |
| `--agent-wait-seconds` | OS Config エージェント起動待機秒数 | `90` |

### 実行後のクリーンアップ

不要になった OSPolicyAssignment は削除してください。

```bash
python os_policy_assignment.py --delete <assignment-id> --zone <zone>
```

---

## os_policy_assignment.py

OS Config の OSPolicyAssignment を作成し、GCE インスタンスに任意のシェルコマンドを送信します。

### 仕組み

`ExecResource` の2フェーズ実行を利用します。

| フェーズ | 動作 | 終了コード |
|---|---|---|
| validate | 常に enforce フェーズを実行させる | `101` |
| enforce | 指定されたコマンドを実行する | `100` (成功) |

終了コードの意味:

| 終了コード | 意味 |
|---|---|
| `100` | 既に望ましい状態 (enforce フェーズをスキップ) |
| `101` | 望ましい状態ではない (enforce フェーズを実行) |
| その他 | エラー |

### コマンドを送信する

ゾーン内の全インスタンスに対してコマンドを送信します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_ZONE=asia-northeast1-a
python os_policy_assignment.py --command "df -h"
```

### ラベルで対象インスタンスを絞り込む

`--label-key` / `--label-value` で対象インスタンスをラベルで絞り込めます。

```bash
python os_policy_assignment.py \
  --command "echo hello" \
  --label-key env \
  --label-value dev
```

### Assignment ID を指定する

`--assignment-id` で OSPolicyAssignment の ID を指定できます（省略時は自動生成）。

```bash
python os_policy_assignment.py \
  --command "systemctl restart nginx" \
  --assignment-id restart-nginx-20260414
```

### オプション一覧

| オプション | 説明 | デフォルト |
|---|---|---|
| `--command` | 実行するシェルコマンド | ─ |
| `--zone` | ターゲットゾーン | 環境変数 `GOOGLE_CLOUD_ZONE` または `asia-northeast1-a` |
| `--assignment-id` | OSPolicyAssignment の ID | 自動生成 (`cmd-<uuid>`) |
| `--label-key` | インスタンスフィルター用ラベルキー | ─ (全インスタンスが対象) |
| `--label-value` | インスタンスフィルター用ラベル値 | ─ (全インスタンスが対象) |
| `--list` | OSPolicyAssignment の一覧を表示 | ─ |
| `--delete ASSIGNMENT_ID` | 指定 ID の OSPolicyAssignment を削除 | ─ |

### OSPolicyAssignment の一覧を表示する

```bash
python os_policy_assignment.py --list
```

### OSPolicyAssignment を削除する

```bash
python os_policy_assignment.py --delete <assignment-id>
```

---

## 参考

- [OS Config Python クライアントライブラリ](https://docs.cloud.google.com/python/docs/reference/osconfig/latest)
- [OS ポリシーと OS ポリシーの割り当て](https://cloud.google.com/compute/docs/os-configuration-management/working-with-os-policies)
- [OS Config エージェント](https://cloud.google.com/compute/docs/manage-os/install-osconfig-agent)
