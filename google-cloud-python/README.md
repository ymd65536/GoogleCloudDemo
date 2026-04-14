# google-cloud-python サンプル集

`google-cloud-python` ライブラリを使って Google Cloud リソースを操作するサンプルスクリプト集です。

## 前提条件

### インストール

```bash
pip install google-cloud-compute google-cloud-artifact-registry google-cloud-sqladmin
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

### 共通の環境変数

| 環境変数 | 説明 | デフォルト |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | プロジェクトID | ADCから自動取得 |
| `GOOGLE_CLOUD_ZONE` | ゾーン (Compute Engine) | スクリプトごとに異なる |
| `GOOGLE_CLOUD_INSTANCE` | 対象インスタンス名 (Compute Engine) | なし (必須) |
| `GOOGLE_CLOUD_REGION` | リージョン (Cloud SQL) | `asia-northeast1` |
| `GOOGLE_CLOUD_SQL_INSTANCE` | 対象インスタンス名 (Cloud SQL) | なし (必須) |

---

## Compute Engine

### インスタンス一覧の取得 (ゾーン指定)

指定ゾーンのインスタンス一覧を取得します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_ZONE=asia-northeast1-a  # 省略時は us-central1-a
python compute_engine/compute_engine.py
```

### インスタンス一覧の取得 (全ゾーン)

プロジェクト内の全ゾーンのインスタンスを一括取得します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python compute_engine/get_compute_engine.py
```

### インスタンスの作成

新しい Compute Engine インスタンスを作成します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python compute_engine/create_compute_engine.py --instance my-vm
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--instance` | インスタンス名 (必須) | 環境変数 `GOOGLE_CLOUD_INSTANCE` |
| `--zone` | ゾーン | `asia-northeast1-a` |
| `--machine-type` | マシンタイプ | `e2-micro` |
| `--image-family` | ブートイメージファミリー | `debian-12` |
| `--image-project` | イメージのプロジェクト | `debian-cloud` |
| `--disk-size` | ブートディスクサイズ (GB) | `10` |

```bash
# オプション指定の例
python compute_engine/create_compute_engine.py \
  --zone asia-northeast1-a \
  --instance my-vm \
  --machine-type e2-standard-2 \
  --disk-size 20
```

### インスタンスの起動

停止中 (TERMINATED) のインスタンスを起動します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python compute_engine/start_compute_engine.py --instance my-vm
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--instance` | インスタンス名 (必須) | 環境変数 `GOOGLE_CLOUD_INSTANCE` |
| `--zone` | ゾーン | `asia-northeast1-a` |

### インスタンスの停止

実行中 (RUNNING) のインスタンスを停止します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python compute_engine/stop_compute_engine.py --instance my-vm
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--instance` | インスタンス名 (必須) | 環境変数 `GOOGLE_CLOUD_INSTANCE` |
| `--zone` | ゾーン | `asia-northeast1-a` |

### インスタンスの再起動

インスタンスを再起動します。再起動方式を選択できます。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id

# ハードリセット (デフォルト): reset API で即時リセット
python compute_engine/restart_compute_engine.py --instance my-vm

# ソフトリスタート: グレースフルに stop → start
python compute_engine/restart_compute_engine.py --instance my-vm --soft
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--instance` | インスタンス名 (必須) | 環境変数 `GOOGLE_CLOUD_INSTANCE` |
| `--zone` | ゾーン | `asia-northeast1-a` |
| `--hard` | ハードリセット (即時リセット) | デフォルト |
| `--soft` | ソフトリスタート (stop → start) | — |

**ハードリセット vs ソフトリスタートの違い:**

| 方式 | API | 挙動 |
|---|---|---|
| `--hard` | `reset()` | インスタンスを強制リセット。状態は RUNNING のまま |
| `--soft` | `stop()` → `start()` | グレースフルなシャットダウン後に起動 |

---

## Cloud SQL

> **注意:** Cloud SQL に「start / stop」という明示的な API はなく、`activationPolicy` の変更で起動・停止を制御します。

### インスタンス一覧の取得

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python cloud_sql/list_cloud_sql.py
```

### インスタンスの作成

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python cloud_sql/create_cloud_sql.py --instance my-db
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--instance` | インスタンス名 (必須) | 環境変数 `GOOGLE_CLOUD_SQL_INSTANCE` |
| `--region` | リージョン | `asia-northeast1` |
| `--db-version` | DBバージョン | `MYSQL_8_0` |
| `--tier` | マシンティア | `db-f1-micro` |
| `--storage-size` | ストレージサイズ GB | `10` |
| `--storage-type` | ストレージ種別 `PD_SSD` / `PD_HDD` | `PD_SSD` |

```bash
# オプション指定の例 (PostgreSQL 15)
python cloud_sql/create_cloud_sql.py \
  --instance my-db \
  --db-version POSTGRES_15 \
  --tier db-n1-standard-1 \
  --storage-size 20
```

**主な `--db-version` の値:**

| 値 | 説明 |
|---|---|
| `MYSQL_8_0` | MySQL 8.0 |
| `POSTGRES_15` | PostgreSQL 15 |
| `SQLSERVER_2022_EXPRESS` | SQL Server 2022 Express |

### インスタンスの起動

`activationPolicy` を `ALWAYS` に設定して起動します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python cloud_sql/start_cloud_sql.py --instance my-db
```

### インスタンスの停止

`activationPolicy` を `NEVER` に設定して停止します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python cloud_sql/stop_cloud_sql.py --instance my-db
```

### インスタンスの再起動

実行中のインスタンスを再起動します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python cloud_sql/restart_cloud_sql.py --instance my-db
```

---

## Artifact Registry

### リポジトリ一覧の取得

指定ロケーションの Artifact Registry リポジトリ一覧を取得します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=asia-northeast1  # 省略時は asia-northeast1
python artifact_registry/artifact_registry.py
```

---

## ファイル構成

```
google-cloud-python/
├── gcp_auth.py                          # ADC を使った認証ヘルパー
├── compute_engine/
│   ├── compute_engine.py                # インスタンス一覧取得 (ゾーン指定)
│   ├── get_compute_engine.py            # インスタンス一覧取得 (全ゾーン)
│   ├── create_compute_engine.py         # インスタンス作成
│   ├── start_compute_engine.py          # インスタンス起動
│   ├── stop_compute_engine.py           # インスタンス停止
│   └── restart_compute_engine.py        # インスタンス再起動
├── cloud_sql/
│   ├── list_cloud_sql.py                # インスタンス一覧取得
│   ├── create_cloud_sql.py              # インスタンス作成
│   ├── start_cloud_sql.py               # インスタンス起動
│   ├── stop_cloud_sql.py                # インスタンス停止
│   └── restart_cloud_sql.py             # インスタンス再起動
└── artifact_registry/
    └── artifact_registry.py             # リポジトリ一覧取得
```
