# Senhub IoTシステム — 工場用IoT サーバー/API 基本設計

## Context

工場用IoTシステム向け。センサー値（連続データ）と機器のON/OFF状態（イベントデータ）を
統合して管理するSenhubを設計する。
- ライブラリAPIはAmbientと同じ操作感（begin / set / send）
- HTTP通信はテキストベース（ArduinoJson不要）
- デフォルトエンドポイント: `https://senhub.hide23.link`（ドメイン・ポートは設定変更可）
- 構成: ESP32 ↔ FastAPI（senhub.hide23.link）+ TimescaleDB
- ライブラリ配布: GitHub `hide23link/senhub`（Python pip / Arduino ZIP）

---

## システム構成

```
[センサー/機器] → [ESP32 + Senhub.h]
                    │ センサー値: バッファ送信（10件 or 30秒）
                    │ ON/OFF変化: 即時送信（バッファしない）
                    ↓ HTTPS (senhub.hide23.link / 443)
               [FastAPI + uvicorn サーバー]
                    ├─ Writer:        TimescaleDB書き込み
                    ├─ Event Engine:  ON/OFF状態管理・稼働時間集計
                    └─ REST API:      データ取得/エクスポート/稼働レポート
               [TimescaleDB（PostgreSQL 16拡張）]
                    ├─ channels           (チャンネル認証キー管理)
                    ├─ channel_properties (フィールドメタ情報)
                    ├─ sensor_data        (連続センサー値・Hypertable)
                    ├─ events             (ON/OFF状態変化ログ・Hypertable)
                    ├─ sensor_data_1min   (1分集約 Continuous Aggregate)
                    └─ sensor_data_1hour  (1時間集約 Continuous Aggregate)
               [Grafana]
                    └─ TimescaleDB に PostgreSQL データソースで直接接続
```

---

## Python ライブラリ API

```python
import senhub

s = senhub.Senhub(100, "your_writeKey", readKey="your_readKey")

# センサーデータ送信
r = s.send({"d1": temp, "d2": humid})

# 機器状態送信（ON=1 / OFF=0）
r = s.send({"d3": 1})   # 機器ON
r = s.send({"d3": 0})   # 機器OFF
```

| メソッド | 認証 | 説明 |
|---------|------|------|
| `Senhub(channelId, writeKey, readKey="")` | — | 初期化 |
| `send({"d1": v, ...})` | writeKey | データ送信（d1〜d8、数値 or 0/1）|
| `read(n=100)` | readKey | 最新N件取得（最大 10,000）|
| `read(date="YYYY-MM-DD")` | readKey | 日付指定取得 |
| `read(start="...", end="...", resolution="1min")` | readKey | 期間+解像度指定 |
| `export(format="csv", start="...", end="...")` | readKey | データエクスポート |
| `getprop()` | **readKey 必須** | チャネル設定取得 |
| `setprop({...})` | writeKey | チャネル設定更新 |

---

## Arduino（ESP32）ライブラリ API

```cpp
#include "Senhub.h"

Senhub senhub;
WiFiClient client;

bool lastMachineState = false;

void setup() {
    WiFi.begin(ssid, password);
    while (WiFi.status() != WL_CONNECTED) delay(500);
    senhub.begin(channelId, writeKey, &client);  // Ambientと同じ
}

void loop() {
    // センサー値（バッファ送信）
    float temp  = readTemperature();
    float humid = readHumidity();
    senhub.set(1, temp);
    senhub.set(2, humid);
    senhub.send();   // 10件 or 30秒で自動送信

    // 機器ON/OFF（状態変化時のみ即時送信）
    bool machineOn = digitalRead(MACHINE_PIN);
    if (machineOn != lastMachineState) {
        senhub.setEvent(3, machineOn ? 1 : 0);  // d3: 機器状態
        senhub.sendEvent();                       // 即時送信（バッファしない）
        lastMachineState = machineOn;
    }

    delay(1000);
}
```

| メソッド | 説明 |
|---------|------|
| `begin(channelId, writeKey, &client)` | 初期化（Ambientと同じ）|
| `set(fieldNo, value)` | センサー値をセット（int/float/char*）|
| `send()` | バッファに蓄積、**10件 or 30秒**でHTTP送信 |
| `setEvent(fieldNo, 0or1)` | ON/OFF状態をセット |
| `sendEvent()` | **即時**HTTP送信（バッファしない）|

---

## HTTP通信フォーマット（テキストベース）

### センサーバッチ送信（ESP32 本番）
```
POST https://senhub.hide23.link/api/v1/channels/{channelId}/dataarray
Content-Type: text/plain

writeKey=KEY
1716451200,23.5,60.2,,,,,,
1716451201,23.6,60.1,,,,,,
```
行フォーマット：`UNIXタイムスタンプ,d1,d2,d3,d4,d5,d6,d7,d8`

### ON/OFFイベント即時送信
```
POST https://senhub.hide23.link/api/v1/channels/{channelId}/event
Content-Type: text/plain

writeKey=KEY
1716451300,3,1
```
行フォーマット：`UNIXタイムスタンプ,フィールド番号,状態(0or1)`

### 単発書き込み（デバッグ・Python用）
```
GET https://senhub.hide23.link/api/v1/channels/{channelId}/data?writeKey=KEY&d1=23.5&d2=60.2
```

### データ取得
```
GET https://senhub.hide23.link/api/v1/channels/{channelId}/data?readKey=KEY&n=100
GET https://senhub.hide23.link/api/v1/channels/{channelId}/data?readKey=KEY&start=...&end=...&resolution=1min
```

---

## サーバー側 APIエンドポイント一覧

### データ書き込み

| エンドポイント | 認証 | 用途 |
|--------------|------|------|
| `GET  /api/v1/channels/{id}/data?writeKey=...&d1=...` | writeKey | 単発書き込み |
| `POST /api/v1/channels/{id}/dataarray` | writeKey（ボディ）| センサーバッチ送信（本番）|
| `POST /api/v1/channels/{id}/event` | writeKey（ボディ）| **ON/OFFイベント即時送信** |

### データ読み取り・表示

| エンドポイント | 認証 | 用途 |
|--------------|------|------|
| `GET /api/v1/channels/{id}/data?readKey=...&n=100` | readKey | 最新N件 |
| `GET /api/v1/channels/{id}/data?...&resolution=1min` | readKey | 集約データ |
| `GET /api/v1/channels/{id}/export?readKey=...&format=csv` | readKey | CSVエクスポート |
| `GET /api/v1/channels/{id}/state?readKey=...` | readKey | 各フィールドの現在ON/OFF状態 |
| `GET /api/v1/channels/{id}/events?readKey=...&n=100` | readKey | ON/OFFイベント履歴 |
| `GET /api/v1/channels/{id}/uptime?readKey=...&field=3&start=...&end=...` | readKey | 稼働時間・稼働率 |

### チャネル設定・デバッグ

| エンドポイント | 認証 | 用途 |
|--------------|------|------|
| `GET  /api/v1/channels/{id}/properties?readKey=...` | readKey | フィールド設定取得 |
| `POST /api/v1/channels/{id}/properties?writeKey=...` | writeKey | フィールド設定更新 |
| `GET  /api/v1/channels/{id}/debug?readKey=...` | readKey | デバッグ情報 |

### バリデーション仕様

| パラメータ | 制約 | 不正時 |
|-----------|------|-------|
| `n` | 最大 10,000 | 400 |
| `date` | `YYYY-MM-DD` 形式 | 400 |
| `start` / `end` | ISO 8601 形式 | 400 |
| `resolution` | `raw` / `1min` / `1hour` のみ | 400 |
| イベント `field` | 1〜8 | スキップ（カウントなし）|
| イベント `state` | 0 または 1 | スキップ |
| `field` (`/uptime`) | 1〜8 | 400 |

---

## データベース設計（TimescaleDB）

```sql
-- チャンネル認証キー管理
CREATE TABLE channels (
    channel_id   INTEGER      PRIMARY KEY,
    write_key    VARCHAR(128) NOT NULL,
    read_key     VARCHAR(128) NOT NULL,
    name         VARCHAR(128) NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- フィールドメタ情報（name / unit / type）
CREATE TABLE channel_properties (
    channel_id  INTEGER     NOT NULL REFERENCES channels(channel_id) ON DELETE CASCADE,
    field       VARCHAR(4)  NOT NULL,   -- "d1"〜"d8"
    name        VARCHAR(64)  NOT NULL DEFAULT '',
    unit        VARCHAR(32)  NOT NULL DEFAULT '',
    type        VARCHAR(16)  NOT NULL DEFAULT 'sensor',  -- "sensor" or "event"
    PRIMARY KEY (channel_id, field)
);

-- 連続センサーデータ（Hypertable）
CREATE TABLE sensor_data (
    time        TIMESTAMPTZ NOT NULL,
    channel_id  INTEGER     NOT NULL,
    d1 DOUBLE PRECISION, d2 DOUBLE PRECISION,
    d3 DOUBLE PRECISION, d4 DOUBLE PRECISION,
    d5 DOUBLE PRECISION, d6 DOUBLE PRECISION,
    d7 DOUBLE PRECISION, d8 DOUBLE PRECISION
);
SELECT create_hypertable('sensor_data', by_range('time'));

-- ON/OFFイベントログ（Hypertable）
CREATE TABLE events (
    time        TIMESTAMPTZ NOT NULL,
    channel_id  INTEGER     NOT NULL,
    field       SMALLINT    NOT NULL,   -- d1〜d8 のどのフィールドか
    state       SMALLINT    NOT NULL,   -- 0=OFF / 1=ON
    duration    INTEGER                 -- OFF時に直前ON継続時間（秒）を確定記録
);
SELECT create_hypertable('events', by_range('time'));

-- 1分・1時間の自動集約（Continuous Aggregate）
CREATE MATERIALIZED VIEW sensor_data_1min  WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', time) AS bucket, channel_id,
       avg(d1) d1, avg(d2) d2, ..., avg(d8) d8
FROM sensor_data GROUP BY bucket, channel_id WITH NO DATA;

CREATE MATERIALIZED VIEW sensor_data_1hour WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour',   time) AS bucket, channel_id,
       avg(d1) d1, ..., avg(d8) d8
FROM sensor_data GROUP BY bucket, channel_id WITH NO DATA;
```

### Grafana連携（TimescaleDB直接接続）

Grafana は **PostgreSQL データソース** から TimescaleDB に直接クエリする。  
FastAPI API は経由しない。

```sql
-- センサーグラフ（d1 温度の時系列）
SELECT time, d1 AS "温度(℃)" FROM sensor_data
WHERE channel_id = 100 AND $__timeFilter(time) ORDER BY time ASC;

-- 1分平均グラフ
SELECT bucket AS time, d1 AS "温度(℃)" FROM sensor_data_1min
WHERE channel_id = 100 AND $__timeFilter(bucket);

-- 機器稼働状態（ON=1/OFF=0）
SELECT time, state AS "機器状態" FROM events
WHERE channel_id = 100 AND field = 3 AND $__timeFilter(time);

-- 稼働率（期間集計）
SELECT SUM(CASE WHEN state = 0 THEN duration ELSE 0 END)::float
       / EXTRACT(EPOCH FROM ($__timeTo()::timestamptz - $__timeFrom()::timestamptz)) * 100
       AS "稼働率(%)"
FROM events WHERE channel_id = 100 AND field = 3 AND $__timeFilter(time);
```

---

## 認証キー設計

| キー | 保管場所 | 用途 |
|-----|---------|------|
| `channelId` | ESP32 / Python 両方 | チャネル識別 |
| `writeKey` | **ESP32のみ** | 書き込み・イベント送信・設定更新 |
| `readKey` | **Python / 管理画面のみ** | 読み込み・統計・エクスポート・設定取得 |

### セキュリティ実装

- キー比較: `hmac.compare_digest()` でタイミング攻撃対策
- `channels.yaml` が存在する場合、未定義チャンネルは全エンドポイントで 404
- `/docs` `/redoc` は `SENHUB_DEBUG=true` のときのみ有効（デフォルト無効）
- `POST /dataarray` / `POST /event` のボディサイズ上限: 1MB
- n パラメータ上限: 10,000件

---

## ネットワーク・DNS・TLS

### 接続先の設定変更

ドメイン・ポートは設定ファイルと引数で変更可能。ハードコードしない。

#### サーバー側（`server/.env`）

```bash
cp server/.env.example server/.env
```

| 環境変数 | デフォルト | 説明 |
|---------|-----------|------|
| `SENHUB_DOMAIN` | `senhub.hide23.link` | 公開ドメイン名（証明書パスにも使用）|
| `SENHUB_PORT` | `443`（TLS有効時）/ `8000`（無効時）| リッスンポート |
| `SENHUB_USE_TLS` | `true` | HTTPS使用: `true` / HTTP使用: `false` |
| `SENHUB_TLS_CERT` | `/etc/letsencrypt/live/{DOMAIN}/fullchain.pem` | TLS証明書パス |
| `SENHUB_TLS_KEY` | `/etc/letsencrypt/live/{DOMAIN}/privkey.pem` | TLS秘密鍵パス |
| `SENHUB_DB_URL` | なし | TimescaleDB 接続URL（未設定でメモリモード）|
| `SENHUB_DEBUG` | `false` | `true` のとき `/docs` を公開（開発専用）|

#### ケース別設定例

| 環境 | `SENHUB_DOMAIN` | `SENHUB_PORT` | `SENHUB_USE_TLS` |
|-----|----------------|--------------|----------------|
| 本番（senhub.hide23.link） | `senhub.hide23.link` | `443` | `true` |
| 別ドメイン（非標準ポート） | `myserver.example.com` | `8443` | `true` |
| 社内 LAN（IP直打ち） | `192.168.1.100` | `8000` | `false` |
| ローカル開発 | `localhost` | `8000` | `false` |

#### サーバー起動

```bash
# .env の設定を自動読み込みして起動
python server/main.py

# 設定を上書きして起動（環境変数が .env より優先される）
SENHUB_DOMAIN=myserver.example.com SENHUB_PORT=8443 python server/main.py
```

---

### ポート指定とTLSの関係

| 接続形式 | URL例 | Arduino クライアント | 証明書 |
|---------|-------|-------------------|--------|
| HTTPS 443（標準） | `https://senhub.hide23.link/api/v1` | `WiFiClientSecure` | ISRG Root X1 |
| HTTPS 非標準ポート | `https://myserver.com:8443/api/v1` | `WiFiClientSecure` | 対応ルートCA |
| HTTP（社内LAN） | `http://192.168.1.100:8000/api/v1` | `WiFiClient` | 不要 |
| HTTP（ローカル開発） | `http://localhost:8000/api/v1` | `WiFiClient` | 不要 |

---

### DNS構成

| レコード種別 | 名前 | 値 |
|------------|------|-----|
| **A**    | `senhub.hide23.link` | サーバーのグローバルIPv4アドレス |

---

### TLS証明書構成（Let's Encrypt + Certbot）

```
サーバー（192.168.0.92）
├─ Certbot (証明書取得・自動更新 via certbot.timer)
│    /etc/letsencrypt/live/senhub.hide23.link/
│         ├─ fullchain.pem   (証明書) ← SENHUB_TLS_CERT
│         └─ privkey.pem     (秘密鍵) ← SENHUB_TLS_KEY
└─ FastAPI (uvicorn) ← server/.env の設定を読み込んで証明書をロード
```

---

### ESP32側のTLS設定

Let's Encryptのルート証明書（**ISRG Root X1**）をESP32に埋め込む。

```cpp
#include <WiFiClientSecure.h>

// ISRG Root X1 証明書（Let's Encrypt ルートCA）
const char* root_ca = \
"-----BEGIN CERTIFICATE-----\n"
"MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw\n"
// ... (ISRG Root X1 全文)
"-----END CERTIFICATE-----\n";

WiFiClientSecure client;
client.setCACert(root_ca);
senhub.begin(channelId, writeKey, &client);
```

---

## 負荷試算

| 条件 | 値 |
|------|-----|
| センサーサンプリング間隔 | **最大1秒**（通常はそれ以上）|
| 最大日次データ量 | 86,400件/日（1秒時・1台）|
| ON/OFFイベント量 | 数件〜数十件/日（状態変化時のみ）|
| TimescaleDB挿入速度上限 | 1,187件/秒（余裕あり）|

---

## 実装状況・残タスク

### ✅ 完了

- [x] Python ライブラリ（送信・取得・エクスポート・プロパティ）
- [x] Arduino（ESP32）ライブラリ（バッチ送信・イベント送信）
- [x] FastAPI サーバー（DBモード / メモリモード切り替え）
- [x] TimescaleDB スキーマ（Hypertable・Continuous Aggregate）
- [x] チャンネル管理（channels.yaml・gen-channel-keys.py）
- [x] TLS証明書取得（Let's Encrypt, senhub.hide23.link）
- [x] systemd による常時起動（192.168.0.92）
- [x] インストール手順書（インストール.md）
- [x] セキュリティ強化
  - [x] タイミング攻撃対策（hmac.compare_digest）
  - [x] 全エンドポイントの認証必須化
  - [x] 入力バリデーション（date/start/end/resolution/field/n）
  - [x] `/docs` の本番無効化（SENHUB_DEBUG）
  - [x] POST ボディサイズ制限・n 上限制限

### 🔲 残タスク

- [ ] d1〜d8 のフィールド割り当て（センサー種別・ON/OFFの対応表）を定義
- [ ] Grafana 設定（TimescaleDB データソース接続・ダッシュボード作成）
- [ ] アラート通知手段の決定（Webhook / メール / LINE）
- [ ] nginx レート制限設定（ブルートフォース対策）
- [ ] `channels.yaml` の `test_writeKey`/`test_readKey` を本番キーに更新
- [ ] Arduino ライブラリの初回リリース ZIP を作成・GitHub Release に添付
