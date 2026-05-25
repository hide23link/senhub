# Senhub ライブラリ仕様書

バージョン: 0.2.0  
対象: Python ライブラリ / Arduino（ESP32）ライブラリ  
デフォルトエンドポイント: `https://senhub.hide23.link`（設定変更可・後述）

---

## 1. Python ライブラリ仕様

### インストール

```bash
# GitHub から直接インストール（最新 main ブランチ）
pip install "git+https://github.com/hide23link/senhub.git#subdirectory=python"

# バージョン指定（タグ）
pip install "git+https://github.com/hide23link/senhub.git@v0.2.0#subdirectory=python"
```

### インポート

```python
import senhub
```

---

### クラス: `Senhub`

#### コンストラクタ

```python
Senhub(channelId: int, writeKey: str, readKey: str = "", base_url: str = None)
```

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `channelId` | `int` | ✅ | チャネルID |
| `writeKey` | `str` | ✅ | 書き込みキー |
| `readKey` | `str` | ― | 読み込みキー（`read` / `export` / `getprop` 使用時は必須）|
| `base_url` | `str` | ― | 接続先ベースURL（省略時は環境変数 `SENHUB_BASE_URL` → デフォルト値の順に参照）|

**接続先URLの優先順位:**

| 優先順位 | 方法 | 例 |
|---------|------|-----|
| 1（最優先） | コンストラクタ引数 `base_url` | `Senhub(100, key, base_url="http://192.168.1.1:8000/api/v1")` |
| 2 | 環境変数 `SENHUB_BASE_URL` | `export SENHUB_BASE_URL=https://myserver.com/api/v1` |
| 3（デフォルト） | ライブラリ内定数 | `https://senhub.hide23.link/api/v1` |

---

#### データ送信

```python
def send(data: dict) -> int
```

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `data` | `dict` | キー: `"d1"`〜`"d8"` / 値: `int`, `float`, `str` |

**戻り値:** HTTPステータスコード（`200` = 成功）  
**例外:**
- `SenhubValueError` — 不正なフィールド名（d1〜d8 以外）
- `SenhubAuthError` — writeKey 不正
- `SenhubTimeoutError` — タイムアウト

```python
r = s.send({"d1": 23.5, "d2": 60.2})   # センサー値
r = s.send({"d3": 1})                   # 機器ON
r = s.send({"d3": 0})                   # 機器OFF
```

---

#### データ取得

```python
def read(
    n: int = None,
    date: str = None,
    start: str = None,
    end: str = None,
    resolution: str = "raw"
) -> list[dict]
```

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `n` | `int` | 最新N件取得（最大 **10,000**）|
| `date` | `str` | 日付指定 `"YYYY-MM-DD"` |
| `start` | `str` | 開始日時 `"YYYY-MM-DD HH:MM:SS"` |
| `end` | `str` | 終了日時 `"YYYY-MM-DD HH:MM:SS"` |
| `resolution` | `str` | `"raw"` / `"1min"` / `"1hour"`（デフォルト: `"raw"`）|

**戻り値:** データのリスト  
```python
[
    {"created": "2026-05-25 10:00:00", "d1": 23.5, "d2": 60.2, ...},
    ...
]
```
**例外:**
- `SenhubAuthError` — readKey 未設定または不正
- `SenhubValueError` — n が 10,000 超、または resolution が不正値
- `SenhubTimeoutError` — タイムアウト

> **注意:** `resolution` は `"raw"` / `"1min"` / `"1hour"` 以外の値を指定すると
> `SenhubValueError` が発生します（サーバー側も 400 を返します）。

---

#### データエクスポート

```python
def export(
    format: str = "csv",
    start: str = None,
    end: str = None
) -> str
```

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `format` | `str` | `"csv"` / `"json"` |
| `start` / `end` | `str` | エクスポート期間 `"YYYY-MM-DD HH:MM:SS"` |

**戻り値:** CSV文字列 または JSON文字列  
**例外:** `SenhubAuthError`（readKey 未設定または不正）

---

#### チャネル設定取得

```python
def getprop() -> dict
```

> **v0.2.0 変更:** readKey が**必須**になりました。readKey 未設定 or 不正の場合は `SenhubAuthError` が発生します。

**戻り値:**
```python
{
    "channelId": 100,
    "d1": {"name": "温度", "unit": "℃", "type": "sensor"},
    "d2": {"name": "湿度", "unit": "%",  "type": "sensor"},
    "d3": {"name": "機器A", "unit": "",  "type": "event"},
    ...
}
```
**例外:** `SenhubAuthError`（readKey 未設定または不正）

---

#### チャネル設定更新

```python
def setprop(properties: dict) -> bool
```

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `properties` | `dict` | `{"d1": {"name": "温度", "unit": "℃", "type": "sensor"}, ...}` |

`type` は `"sensor"`（連続値）または `"event"`（ON/OFF）を指定。  
**戻り値:** `True`（成功）/ `False`（失敗）  
**例外:**
- `SenhubValueError` — 不正なフィールド名
- `SenhubAuthError` — writeKey 不正

---

### 例外クラス

| 例外 | 発生条件 |
|------|---------|
| `SenhubAuthError` | writeKey / readKey 不正、または未設定 |
| `SenhubTimeoutError` | サーバー応答タイムアウト |
| `SenhubValueError` | 引数の値が不正（フィールド名・resolution・n 上限超えなど）|

---

## 2. Arduino（ESP32）ライブラリ仕様

### インストール

**方法①: GitHub Releases からZIPインストール（推奨）**

1. [https://github.com/hide23link/senhub/releases](https://github.com/hide23link/senhub/releases) から `Senhub-x.x.x.zip` をダウンロード
2. Arduino IDE: **スケッチ → ライブラリをインクルード → .ZIP形式のライブラリをインストール** → ZIPを選択

**方法②: Git clone（開発・最新版）**

```bash
cd ~/Documents/Arduino/libraries
git clone https://github.com/hide23link/senhub.git senhub-repo
# Arduino IDE 2.x が arduino/Senhub/ を自動検出する
```

**リリースZIPの生成（開発者向け）**

```bash
bash scripts/make-arduino-release.sh          # バージョンは library.properties から自動取得
bash scripts/make-arduino-release.sh 0.2.0   # バージョン指定
# → dist/Senhub-0.2.0.zip が生成される
```

### インクルード

```cpp
#include "Senhub.h"
```

---

### 定数

| 定数 | デフォルト値 | 説明 |
|------|------------|------|
| `SENHUB_BATCH_SIZE` | `10` | バッチ送信件数 |
| `SENHUB_BATCH_TIMEOUT` | `30000` | バッチ送信タイムアウト（ms）|
| `SENHUB_MAX_FIELDS` | `8` | フィールド数（d1〜d8）|
| `SENHUB_DEFAULT_URL` | `"https://senhub.hide23.link/api/v1"` | 接続先ベースURL |

**`SENHUB_DEFAULT_URL` の変更方法（2通り）:**

```cpp
// 方法①: #include より前に #define で上書き（スケッチ全体に適用）
#define SENHUB_DEFAULT_URL "https://myserver.example.com/api/v1"
#include "Senhub.h"

// 方法②: begin() の第4引数で個別に指定（インスタンスごと）
senhub.begin(channelId, writeKey, &client, "http://192.168.1.100:8000/api/v1");
```

---

### クラス: `Senhub`

#### 初期化

```cpp
void begin(unsigned int channelId, const char* writeKey, WiFiClient* client,
           const char* baseUrl = SENHUB_DEFAULT_URL)
```

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `channelId` | `unsigned int` | チャネルID |
| `writeKey` | `const char*` | 書き込みキー |
| `client` | `WiFiClient*` | `WiFiClient`（HTTP）または `WiFiClientSecure`（HTTPS）のポインタ |
| `baseUrl` | `const char*` | 接続先ベースURL（省略時: `SENHUB_DEFAULT_URL`）|

**接続先URLの優先順位:**

| 優先順位 | 方法 | 例 |
|---------|------|-----|
| 1（最優先） | `begin()` の `baseUrl` 引数 | `senhub.begin(id, key, &client, "http://192.168.1.1:8000/api/v1")` |
| 2 | `#define SENHUB_DEFAULT_URL` | `#define SENHUB_DEFAULT_URL "https://myserver.com/api/v1"` |
| 3（デフォルト） | ライブラリ内定数 | `https://senhub.hide23.link/api/v1` |

---

#### センサー値セット

```cpp
bool set(int field, int value)
bool set(int field, float value)
bool set(int field, const char* value)
```

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `field` | `int` | フィールド番号 `1`〜`8` |
| `value` | `int` / `float` / `const char*` | セットする値 |

**戻り値:** `true`（成功）/ `false`（フィールド番号範囲外）  
`send()` を呼ぶまで送信されない。

---

#### バッチ送信

```cpp
bool send()
```

- セットされた値をバッファに積む
- **`SENHUB_BATCH_SIZE` 件 または `SENHUB_BATCH_TIMEOUT` 経過**で自動的にHTTP送信
- 送信条件を満たさない場合は `true` を返してバッファに留める

**戻り値:** `true`（バッファ積み込み成功 または 送信成功）/ `false`（送信失敗）

---

#### ON/OFFイベントセット

```cpp
bool setEvent(int field, int state)
```

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `field` | `int` | フィールド番号 `1`〜`8` |
| `state` | `int` | `1`（ON）/ `0`（OFF）|

**戻り値:** `true`（成功）/ `false`（フィールド番号範囲外）  
`sendEvent()` を呼ぶまで送信されない。

---

#### ON/OFFイベント即時送信

```cpp
bool sendEvent()
```

- `setEvent()` でセットした値を**バッファせず即時送信**
- センサーの `send()` バッファとは独立して動作

**戻り値:** `true`（送信成功）/ `false`（送信失敗）

---

#### バッチ設定変更（オプション）

```cpp
void setBatchSize(int size)       // バッチ送信件数（1〜60）
void setBatchTimeout(unsigned long ms)  // タイムアウト（ミリ秒）
```

---

#### 最後のHTTPステータスコード取得

```cpp
int getLastStatus()
```

**戻り値:** 最後の `send()` / `sendEvent()` のHTTPステータスコード  
（`200` = 成功、`0` = 未送信 または 接続失敗）

---

### 使用例

#### 本番サーバー（HTTPS、デフォルト URL）

```cpp
#include <WiFiClientSecure.h>
#include "Senhub.h"

Senhub senhub;
WiFiClientSecure client;

// ISRG Root X1（Let's Encrypt ルートCA）
const char* root_ca = "-----BEGIN CERTIFICATE-----\n ... \n-----END CERTIFICATE-----\n";

void setup() {
    WiFi.begin(ssid, password);
    while (WiFi.status() != WL_CONNECTED) delay(500);

    client.setCACert(root_ca);
    senhub.begin(100, "your_writeKey", &client);   // URL省略 → SENHUB_DEFAULT_URL を使用

    senhub.setBatchSize(10);
    senhub.setBatchTimeout(30000);
}

bool lastState = false;

void loop() {
    senhub.set(1, readTemperature());
    senhub.set(2, readHumidity());
    senhub.send();

    bool current = digitalRead(MACHINE_PIN);
    if (current != lastState) {
        senhub.setEvent(3, current ? 1 : 0);
        senhub.sendEvent();
        lastState = current;
    }
    delay(1000);
}
```

#### 社内 LAN サーバー / ローカル開発（HTTP、ポート指定）

```cpp
#include <WiFiClient.h>
#include "Senhub.h"

Senhub senhub;
WiFiClient client;     // TLS なし → WiFiClient を使用

void setup() {
    WiFi.begin(ssid, password);
    while (WiFi.status() != WL_CONNECTED) delay(500);

    senhub.begin(100, "your_writeKey", &client, "http://192.168.1.100:8000/api/v1");
}
```

#### 別ドメイン・非標準ポート（HTTPS 8443番など）

```cpp
// #define でライブラリ全体のデフォルト URL を変更する場合
// ※ #include より前に記述すること
#define SENHUB_DEFAULT_URL "https://myserver.example.com:8443/api/v1"
#include "Senhub.h"
```

---

## 3. サーバー REST API エンドポイント一覧

### データ書き込み

| エンドポイント | 認証 | 説明 |
|--------------|------|------|
| `GET  /api/v1/channels/{id}/data?writeKey=...&d1=...` | writeKey | 単発書き込み（デバッグ・Python用）|
| `POST /api/v1/channels/{id}/dataarray` | ボディ1行目 `writeKey=...` | バッチ書き込み（ESP32本番）|
| `POST /api/v1/channels/{id}/event` | ボディ1行目 `writeKey=...` | ON/OFFイベント即時送信 |

### データ読み取り

| エンドポイント | 認証 | 説明 |
|--------------|------|------|
| `GET /api/v1/channels/{id}/data?readKey=...&n=100` | readKey | センサーデータ取得 |
| `GET /api/v1/channels/{id}/data?readKey=...&resolution=1min` | readKey | 集約データ取得 |
| `GET /api/v1/channels/{id}/export?readKey=...&format=csv` | readKey | CSVエクスポート |
| `GET /api/v1/channels/{id}/state?readKey=...` | readKey | 各フィールドの現在ON/OFF状態 |
| `GET /api/v1/channels/{id}/events?readKey=...&n=100` | readKey | ON/OFFイベント履歴 |
| `GET /api/v1/channels/{id}/uptime?readKey=...&field=3&start=...&end=...` | readKey | 稼働時間・稼働率 |
| `GET /api/v1/channels/{id}/debug?readKey=...` | readKey | デバッグ情報（最新3件 + モード）|

### チャネル設定

| エンドポイント | 認証 | 説明 |
|--------------|------|------|
| `GET  /api/v1/channels/{id}/properties?readKey=...` | readKey | フィールド設定取得 |
| `POST /api/v1/channels/{id}/properties?writeKey=...` | writeKey | フィールド設定更新 |

### クエリパラメータ（データ取得共通）

| パラメータ | 型 | 説明 | 制約 |
|-----------|-----|------|------|
| `n` | `int` | 最新N件 | 最大 10,000 |
| `date` | `str` | 日付フィルタ `"YYYY-MM-DD"` | 不正形式 → 400 |
| `start` | `str` | 開始日時（ISO 8601）| 不正形式 → 400 |
| `end` | `str` | 終了日時（ISO 8601）| 不正形式 → 400 |
| `resolution` | `str` | `"raw"` / `"1min"` / `"1hour"` | それ以外 → 400 |

---

## 4. フィールド型定義

`getprop()` / `setprop()` で管理するフィールドの `type` 属性。

| type | 用途 | 集約方法 |
|------|------|---------|
| `"sensor"` | 連続センサー値（温度・湿度など）| 平均 |
| `"event"` | 機器ON/OFF状態（0/1）| 最後の値 |

---

## 5. セキュリティ仕様

### 認証

| キー | 保管場所 | 用途 |
|-----|---------|------|
| `writeKey` | **ESP32のみ**（ファームウェア内）| データ書き込み・イベント送信・設定更新 |
| `readKey` | **Python / 管理画面のみ** | データ読み取り・エクスポート・設定取得 |

- すべての読み取り系エンドポイントは `readKey` が**必須**（未指定 → 401）
- すべての書き込み系エンドポイントは `writeKey` が**必須**（未指定 → 401）
- キー比較は `hmac.compare_digest()` でタイミング攻撃対策済み
- `channels.yaml` が存在する場合、未定義チャンネルには全エンドポイントで 404 を返す

### キー生成

```bash
# 新しいチャンネルのキーを生成して channels.yaml に追記
python scripts/gen-channel-keys.py <channel_id> [名前]

# 例
python scripts/gen-channel-keys.py 101 "製造ライン1"
```

生成されるキー形式: `w_` または `r_` + 24桁ランダム16進数（`secrets.token_hex(12)` 使用）

### サーバー側セキュリティ設定

| 設定 | 内容 |
|------|------|
| `SENHUB_DEBUG=false`（デフォルト）| `/docs` `/redoc` `/openapi.json` を無効化 |
| TLS（HTTPS）| Let's Encrypt で自動更新（90日ごと）|
| `MAX_BODY_BYTES=1MB` | POST ボディサイズ上限 |
| `MAX_ROWS=10,000` | `n` パラメータの上限 |

---

## 6. 改訂履歴

| バージョン | 日付 | 内容 |
|----------|------|------|
| 0.1.0 | 2026-05-23 | 初版作成 |
| 0.1.1 | 2026-05-23 | stats / uptime / events / state / アラート関連メソッドを削除 |
| 0.1.2 | 2026-05-24 | 接続先URL・ドメイン・ポートの設定変更方法を追記（Python: `base_url` 引数 / 環境変数、Arduino: `begin()` 第4引数 / `#define`）|
| 0.2.0 | 2026-05-25 | TimescaleDB 接続実装（DBモード/メモリモード切り替え）; サーバーAPIエンドポイント `/state` `/events` `/uptime` を追加; `getprop()` に readKey 必須化; `read()` の n 上限を 10,000 に設定; `resolution` バリデーション追加; セキュリティ仕様セクション追加; デフォルトURLを `senhub.hide23.link` に更新 |
