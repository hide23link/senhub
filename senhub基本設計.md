# Senhub IoTシステム — 工場用IoT サーバー/API 基本設計

## Context

工場用IoTシステム向け。センサー値（連続データ）と機器のON/OFF状態（イベントデータ）を
統合して管理するSenhubを設計する。
- ライブラリAPIはAmbientと同じ操作感（begin / set / send）
- HTTP通信はテキストベース（ArduinoJson不要）
- デフォルトエンドポイント: `https://senhub.hide.link`（ドメイン・ポートは設定変更可）
- 構成: ESP32 ↔ FastAPI（senhub.hide.link）+ TimescaleDB
- ライブラリ配布: GitHub `hide23link/senhub`（Python pip / Arduino ZIP）

---

## システム構成

```
[センサー/機器] → [ESP32 + Senhub.h]
                    │ センサー値: バッファ送信（10件 or 30秒）
                    │ ON/OFF変化: 即時送信（バッファしない）
                    ↓ HTTPS (senhub.hide.link)
               [FastAPI サーバー]
                    ├─ Writer:        TimescaleDB書き込み
                    ├─ Event Engine:  ON/OFF状態管理・稼働時間集計
                    ├─ Alert Engine:  閾値監視・異常停止検知
                    ├─ SSE:           リアルタイム配信 → ブラウザ
                    └─ REST API:      統計/エクスポート/稼働レポート
               [TimescaleDB]
                    ├─ sensor_data   (連続センサー値 1秒〜)
                    ├─ events        (ON/OFF状態変化ログ)
                    ├─ data_1min     (1分集約)
                    └─ data_1hour    (1時間集約)
```

---

## Python ライブラリ API

```python
import senhub

s = senhub.Senhub(100, "your_writeKey")   # チャネルID, ライトキー

# センサーデータ送信
r = s.send({"d1": temp, "d2": humid})

# 機器状態送信（ON=1 / OFF=0）
r = s.send({"d1": 1})   # 機器ON
r = s.send({"d1": 0})   # 機器OFF
```

| メソッド | 説明 |
|---------|------|
| `Senhub(channelId, writeKey, readKey="")` | 初期化 |
| `send({"d1": v, ...})` | データ送信（d1〜d8、数値 or 0/1）|
| `read(n=100)` | 最新N件取得 |
| `read(date="YYYY-MM-DD")` | 日付指定取得 |
| `read(start="...", end="...", resolution="1min")` | 期間+解像度指定 |
| `export(format="csv", start="...", end="...")` | データエクスポート |

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
POST https://senhub.hide.link/api/v1/channels/{channelId}/dataarray
Content-Type: text/plain

writeKey=KEY
1716451200,23.5,60.2,,,,,, 
1716451201,23.6,60.1,,,,,,
```
行フォーマット：`UNIXタイムスタンプ,d1,d2,d3,d4,d5,d6,d7,d8`

### ON/OFFイベント即時送信
```
POST https://senhub.hide.link/api/v1/channels/{channelId}/event
Content-Type: text/plain

writeKey=KEY
1716451300,3,1
```
行フォーマット：`UNIXタイムスタンプ,フィールド番号,状態(0or1)`

### 単発送信（デバッグ・Python用）
```
GET https://senhub.hide.link/api/v1/channels/{channelId}/data?writeKey=KEY&d1=23.5&d2=60.2
```

### データ取得
```
GET https://senhub.hide.link/api/v1/channels/{channelId}/data?readKey=KEY&n=100
GET https://senhub.hide.link/api/v1/channels/{channelId}/data?readKey=KEY&start=...&end=...&resolution=1min
```

---

## サーバー側 APIエンドポイント一覧

### データ受信
| エンドポイント | 用途 |
|--------------|------|
| `GET  /api/v1/channels/{id}/data?writeKey=...&d1=...` | 単発送信（デバッグ）|
| `POST /api/v1/channels/{id}/dataarray` | センサーバッチ送信（本番）|
| `POST /api/v1/channels/{id}/event` | **ON/OFFイベント即時送信** |

### データ取得・表示
| エンドポイント | 用途 |
|--------------|------|
| `GET /api/v1/channels/{id}/data?readKey=...&n=100` | 最新N件 |
| `GET /api/v1/channels/{id}/data?...&resolution=1min` | 集約データ |
| `GET /api/v1/channels/{id}/stream?readKey=...` | SSEリアルタイム配信 |

### エクスポート・設定
| エンドポイント | 用途 |
|--------------|------|
| `GET /api/v1/channels/{id}/export?format=csv&start=...&end=...` | CSVエクスポート |
| `GET /api/v1/channels/{id}/properties` | チャネル設定取得 |

---

## データベース設計（TimescaleDB）

```sql
-- 連続センサーデータ（Hypertable）
CREATE TABLE sensor_data (
  time       TIMESTAMPTZ NOT NULL,
  channel_id INTEGER NOT NULL,
  d1 DOUBLE PRECISION, d2 DOUBLE PRECISION,
  d3 DOUBLE PRECISION, d4 DOUBLE PRECISION,
  d5 DOUBLE PRECISION, d6 DOUBLE PRECISION,
  d7 DOUBLE PRECISION, d8 DOUBLE PRECISION
);
SELECT create_hypertable('sensor_data', 'time');

-- ON/OFFイベントログ（Hypertable）
CREATE TABLE events (
  time       TIMESTAMPTZ NOT NULL,
  channel_id INTEGER NOT NULL,
  field      SMALLINT NOT NULL,   -- d1〜d8 のどのフィールドか
  state      SMALLINT NOT NULL,   -- 0=OFF / 1=ON
  duration   INTEGER              -- 直前の状態の継続時間（秒）※OFF時に確定
);
SELECT create_hypertable('events', 'time');

-- 1分・1時間の自動集約
CREATE MATERIALIZED VIEW sensor_data_1min WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', time) AS bucket, channel_id,
       avg(d1) d1, avg(d2) d2, avg(d3) d3, avg(d4) d4,
       avg(d5) d5, avg(d6) d6, avg(d7) d7, avg(d8) d8
FROM sensor_data GROUP BY bucket, channel_id;
```

---

## アラート設計（工場向け）

| アラート種別 | 条件例 | 用途 |
|------------|--------|------|
| 閾値超過 | `d1 > 80.0` | 温度異常 |
| 閾値下限 | `d2 < 10.0` | 圧力低下 |
| 異常停止 | 稼働中に突然OFF | 機器トラブル |
| 無通信タイムアウト | 5分以上データなし | ESP32/ネットワーク障害 |
| 稼働時間超過 | 連続稼働 > 8時間 | メンテナンス通知 |

```json
// アラートルール例
{
  "field": "d3",
  "condition": "unexpected_off",
  "expected_schedule": "08:00-17:00",
  "action": "webhook",
  "webhook_url": "https://hooks.example.com/..."
}
```

---

## 認証キー設計

| キー | 保管場所 | 用途 |
|-----|---------|------|
| `channelId` | ESP32 / Python 両方 | チャネル識別 |
| `writeKey` | **ESP32のみ** | 書き込み・イベント送信認証 |
| `readKey` | **Python / 管理画面のみ** | 読み込み・統計・エクスポート |

---

## 負荷試算

| 条件 | 値 |
|------|-----|
| センサーサンプリング間隔 | **最大1秒**（通常はそれ以上）|
| 最大日次データ量 | 86,400件/日（1秒時・1台）|
| ON/OFFイベント量 | 数件〜数十件/日（状態変化時のみ）|
| TimescaleDB挿入速度上限 | 1,187件/秒（余裕あり）|

---

## ネットワーク・DNS・TLS

### 接続先の設定変更

ドメイン・ポートは設定ファイルと引数で変更可能。ハードコードしない。

#### サーバー側（`server/.env`）

```bash
# server/.env.example をコピーして編集
cp server/.env.example server/.env
```

| 環境変数 | デフォルト | 説明 |
|---------|-----------|------|
| `SENHUB_DOMAIN` | `senhub.hide.link` | 公開ドメイン名（証明書パスにも使用）|
| `SENHUB_PORT` | `443`（TLS有効時）/ `8000`（無効時）| リッスンポート |
| `SENHUB_USE_TLS` | `true` | HTTPS使用: `true` / HTTP使用: `false` |
| `SENHUB_TLS_CERT` | `/etc/letsencrypt/live/{DOMAIN}/fullchain.pem` | TLS証明書パス |
| `SENHUB_TLS_KEY` | `/etc/letsencrypt/live/{DOMAIN}/privkey.pem` | TLS秘密鍵パス |

#### ケース別設定例

| 環境 | `SENHUB_DOMAIN` | `SENHUB_PORT` | `SENHUB_USE_TLS` |
|-----|----------------|--------------|----------------|
| 本番（senhub.hide.link） | `senhub.hide.link` | `443` | `true` |
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

#### Python ライブラリ側

| 優先順位 | 方法 | 例 |
|---------|------|-----|
| 1 | コンストラクタ引数 | `Senhub(100, key, base_url="http://192.168.1.1:8000/api/v1")` |
| 2 | 環境変数 | `export SENHUB_BASE_URL=https://myserver.example.com/api/v1` |
| 3 | デフォルト | `https://senhub.hide.link/api/v1` |

#### Arduino（ESP32）ライブラリ側

| 優先順位 | 方法 | 例 |
|---------|------|-----|
| 1 | `begin()` 第4引数 | `senhub.begin(id, key, &client, "http://192.168.1.1:8000/api/v1")` |
| 2 | `#define`（`#include`より前）| `#define SENHUB_DEFAULT_URL "https://myserver.com/api/v1"` |
| 3 | デフォルト | `https://senhub.hide.link/api/v1` |

---

### ポート指定とTLSの関係

| 接続形式 | URL例 | Arduino クライアント | 証明書 |
|---------|-------|-------------------|--------|
| HTTPS 443（標準） | `https://senhub.hide.link/api/v1` | `WiFiClientSecure` | ISRG Root X1 |
| HTTPS 非標準ポート | `https://myserver.com:8443/api/v1` | `WiFiClientSecure` | 対応ルートCA |
| HTTP（社内LAN） | `http://192.168.1.100:8000/api/v1` | `WiFiClient` | 不要 |
| HTTP（ローカル開発） | `http://localhost:8000/api/v1` | `WiFiClient` | 不要 |

> **社内LAN・開発環境** では `WiFiClient`（TLSなし）を使うことでLet's Encrypt証明書なしに動作する。  
> **本番・外部公開** では必ず `WiFiClientSecure` + HTTPS を使用する。

---

### DNS構成（Route 53）

| レコード種別 | 名前 | 値 |
|------------|------|-----|
| **A**    | `senhub.hide.link` | 自前サーバーのIPv4アドレス |
| **AAAA** | `senhub.hide.link` | 自前サーバーのIPv6アドレス（あれば）|

ACMは自前サーバーに使用不可のため **Let's Encrypt + Certbot** でTLS証明書を取得・管理する。

---

### TLS証明書構成（Let's Encrypt + Certbot）

```
自前サーバー
├─ Certbot (証明書取得・自動更新)
│    /etc/letsencrypt/live/{SENHUB_DOMAIN}/
│         ├─ fullchain.pem   (証明書) ← SENHUB_TLS_CERT
│         └─ privkey.pem     (秘密鍵) ← SENHUB_TLS_KEY
└─ FastAPI (uvicorn) ← server/.env の設定を読み込んで証明書をロード
```

#### 初回取得
```bash
# HTTP-01チャレンジ（ポート80が開いている場合）
certbot certonly --standalone -d senhub.hide.link

# DNS-01チャレンジ（Route 53プラグイン使用・ポート80不要）
pip install certbot-dns-route53
certbot certonly --dns-route53 -d senhub.hide.link
```

#### 自動更新（systemdタイマー または cron）
```bash
# cron例（毎日2回チェック）
0 0,12 * * * certbot renew --quiet --post-hook "systemctl restart senhub"
```

#### FastAPI（uvicorn）でのTLS設定

`server/.env` に設定を記述し、`python server/main.py` で起動する（推奨）。  
uvicorn を直接起動する場合は以下のとおり：

```bash
uvicorn main:app \
  --host 0.0.0.0 \
  --port 443 \
  --ssl-certfile /etc/letsencrypt/live/senhub.hide.link/fullchain.pem \
  --ssl-keyfile  /etc/letsencrypt/live/senhub.hide.link/privkey.pem
```

---

### ESP32側のTLS設定

Let's Encryptのルート証明書（**ISRG Root X1**）をESP32に埋め込む。  
社内LAN・HTTP接続の場合は `WiFiClient` を使い、この設定は不要。

```cpp
#include <WiFiClientSecure.h>

// ISRG Root X1 証明書（Let's Encrypt ルートCA）
const char* root_ca = \
"-----BEGIN CERTIFICATE-----\n"
"MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw\n"
// ... (ISRG Root X1 全文)
"-----END CERTIFICATE-----\n";

WiFiClientSecure client;

void setup() {
    WiFi.begin(ssid, password);
    while (WiFi.status() != WL_CONNECTED) delay(500);

    client.setCACert(root_ca);              // ルートCA証明書を設定
    senhub.begin(channelId, writeKey, &client);
    // 別サーバーに接続する場合は第4引数で指定:
    // senhub.begin(channelId, writeKey, &client, "https://myserver.com:8443/api/v1");
}
```

| 項目 | 値 |
|------|----|
| デフォルト公開ドメイン | `senhub.hide.link`（`SENHUB_DOMAIN` で変更可）|
| デフォルトプロトコル | HTTPS（ポート443）（`SENHUB_PORT` / `SENHUB_USE_TLS` で変更可）|
| 証明書管理 | Let's Encrypt（90日ごと自動更新）|
| ESP32ルートCA | ISRG Root X1（Let's Encrypt標準）|
| ESP32クライアント | HTTPS: `WiFiClientSecure` / HTTP: `WiFiClient` |

---

## 残タスク

- [ ] d1〜d8 のフィールド割り当て（センサー種別・ON/OFFの対応表）を定義
- [ ] アラート通知手段の決定（Webhook / メール / LINE）
- [ ] 無通信タイムアウト時間の決定
- [ ] グラフ表示UIの実装方法を決定
- [ ] TLS証明書の取得・設定（`certbot certonly --dns-route53 -d senhub.hide.link`）
- [ ] `server/.env.example` を参考に本番用 `server/.env` を作成・設定
- [ ] GitHub リポジトリ `hide23link/senhub` を作成・プッシュ
- [ ] Arduino ライブラリの初回リリース ZIP を作成・GitHub Release に添付（`bash scripts/make-arduino-release.sh`）
