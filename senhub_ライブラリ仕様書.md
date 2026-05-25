# Senhub ライブラリ仕様書

バージョン: 0.1.2  
対象: Python ライブラリ / Arduino（ESP32）ライブラリ  
デフォルトエンドポイント: `https://senhub.hide.link`（設定変更可・後述）

---

## 1. Python ライブラリ仕様

### インストール

```bash
# GitHub から直接インストール（最新 main ブランチ）
pip install "git+https://github.com/hide23link/senhub.git#subdirectory=python"

# バージョン指定（タグ）
pip install "git+https://github.com/hide23link/senhub.git@v0.1.2#subdirectory=python"
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
| `readKey` | `str` | ― | 読み込みキー（読み込み系メソッドを使う場合は必須）|
| `base_url` | `str` | ― | 接続先ベースURL（省略時は環境変数 `SENHUB_BASE_URL` → デフォルト値の順に参照）|

**接続先URLの優先順位:**

| 優先順位 | 方法 | 例 |
|---------|------|-----|
| 1（最優先） | コンストラクタ引数 `base_url` | `Senhub(100, key, base_url="http://192.168.1.1:8000/api/v1")` |
| 2 | 環境変数 `SENHUB_BASE_URL` | `export SENHUB_BASE_URL=https://myserver.com/api/v1` |
| 3（デフォルト） | ライブラリ内定数 | `https://senhub.hide.link/api/v1` |

---

#### データ送信

```python
def send(data: dict) -> int
```

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `data` | `dict` | キー: `"d1"`〜`"d8"` / 値: `int`, `float`, `str` |

**戻り値:** HTTPステータスコード（`200` = 成功）  
**例外:** `SenhubAuthError` — writeKey不正  

```python
# 例
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
| `n` | `int` | 最新N件取得（最大 3,000）|
| `date` | `str` | 日付指定 `"YYYY-MM-DD"` |
| `start` | `str` | 開始日時 `"YYYY-MM-DD HH:MM:SS"` |
| `end` | `str` | 終了日時 `"YYYY-MM-DD HH:MM:SS"` |
| `resolution` | `str` | `"raw"` / `"1min"` / `"1hour"`（デフォルト: `"raw"`）|

**戻り値:** データのリスト  
```python
[
    {"created": "2026-05-23 10:00:00", "d1": 23.5, "d2": 60.2, ...},
    ...
]
```
**例外:** `SenhubAuthError` — readKey不正

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
| `start` / `end` | `str` | エクスポート期間 |

**戻り値:** CSV文字列 または JSON文字列

---

#### チャネル設定取得

```python
def getprop() -> dict
```

**戻り値:**
```python
{
    "channelId": 100,
    "d1": {"name": "温度", "unit": "℃", "type": "sensor"},
    "d2": {"name": "湿度", "unit": "%", "type": "sensor"},
    "d3": {"name": "機器A", "unit": "",  "type": "event"},
    ...
}
```

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

---

### 例外クラス

| 例外 | 発生条件 |
|------|---------|
| `SenhubAuthError` | writeKey / readKey 不正 |
| `SenhubTimeoutError` | サーバー応答タイムアウト |
| `SenhubValueError` | 引数の値が不正（フィールド名など）|

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
bash scripts/make-arduino-release.sh 0.1.2   # バージョン指定
# → dist/Senhub-0.1.2.zip が生成される
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
| `SENHUB_DEFAULT_URL` | `"https://senhub.hide.link/api/v1"` | 接続先ベースURL |

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
| 3（デフォルト） | ライブラリ内定数 | `https://senhub.hide.link/api/v1` |

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
void setBatchSize(int size)
```

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `size` | `int` | バッチ送信件数（1〜60）|

```cpp
void setBatchTimeout(unsigned long ms)
```

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `ms` | `unsigned long` | タイムアウト（ミリ秒）|

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

    // begin() 第4引数で接続先を指定（IP:ポート 形式も可）
    senhub.begin(100, "your_writeKey", &client, "http://192.168.1.100:8000/api/v1");
}
```

#### 別ドメイン・非標準ポート（HTTPS 8443番など）

```cpp
// #define でライブラリ全体のデフォルト URL を変更する場合
// ※ #include より前に記述すること
#define SENHUB_DEFAULT_URL "https://myserver.example.com:8443/api/v1"
#include "Senhub.h"

// begin() でも同様に指定可能
// senhub.begin(100, key, &client, "https://myserver.example.com:8443/api/v1");
```

---

## 3. フィールド型定義

`getprop()` / `setprop()` で管理するフィールドの `type` 属性。

| type | 用途 | 集約方法 |
|------|------|---------|
| `"sensor"` | 連続センサー値（温度・湿度など）| 平均 |
| `"event"` | 機器ON/OFF状態（0/1）| 最後の値 |

---

## 4. 改訂履歴

| バージョン | 日付 | 内容 |
|----------|------|------|
| 0.1.0 | 2026-05-23 | 初版作成 |
| 0.1.1 | 2026-05-23 | stats / uptime / events / state / アラート関連メソッドを削除 |
| 0.1.2 | 2026-05-24 | 接続先URL・ドメイン・ポートの設定変更方法を追記（Python: `base_url` 引数 / 環境変数、Arduino: `begin()` 第4引数 / `#define`）|
