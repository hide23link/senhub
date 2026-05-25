# Senhub

工場用IoTシステム向けライブラリ。センサー値（連続データ）と機器のON/OFF状態（イベントデータ）を ESP32 から Senhub サーバーに送信します。

- **本番エンドポイント**: `https://senhub.hide23.link`
- **Ambientと同じ操作感**: `begin` / `set` / `send`
- **永続ストレージ**: TimescaleDB（PostgreSQL拡張）

---

## インストール

### Python ライブラリ

```bash
pip install "git+https://github.com/hide23link/senhub.git#subdirectory=python"
```

バージョン指定:

```bash
pip install "git+https://github.com/hide23link/senhub.git@v0.2.0#subdirectory=python"
```

### Arduino（ESP32）ライブラリ

**方法①: GitHub Releases からZIPをダウンロード（推奨）**

1. [Releases](https://github.com/hide23link/senhub/releases) から `Senhub-x.x.x.zip` をダウンロード
2. Arduino IDE: スケッチ → ライブラリをインクルード → .ZIP形式のライブラリをインストール → ZIPを選択

**方法②: Git clone（開発・最新版）**

```bash
cd ~/Documents/Arduino/libraries
git clone https://github.com/hide23link/senhub.git senhub-repo
# Arduino IDE 2.x はサブディレクトリの library.properties を自動検出します:
#   ~/Documents/Arduino/libraries/senhub-repo/arduino/Senhub/
```

---

## クイックスタート

### Python

```python
import senhub

s = senhub.Senhub(100, "your_writeKey", readKey="your_readKey")

# センサー値送信
s.send({"d1": 23.5, "d2": 60.2})

# 機器 ON/OFF 送信
s.send({"d3": 1})   # ON
s.send({"d3": 0})   # OFF

# データ取得
data = s.read(n=100)

# プロパティ取得（readKey 必須）
prop = s.getprop()
```

### Arduino（ESP32）

```cpp
#include <WiFiClientSecure.h>
#include "Senhub.h"

Senhub senhub;
WiFiClientSecure client;

void setup() {
    WiFi.begin(ssid, password);
    while (WiFi.status() != WL_CONNECTED) delay(500);

    client.setCACert(root_ca);   // ISRG Root X1 証明書
    senhub.begin(100, "your_writeKey", &client);
}

void loop() {
    senhub.set(1, readTemperature());
    senhub.set(2, readHumidity());
    senhub.send();   // 10件 or 30秒で自動送信
    delay(1000);
}
```

### 接続先の変更（社内LAN・別ドメイン）

| 用途 | URL例 | Arduino クライアント |
|------|-------|-------------------|
| 本番 HTTPS | `https://senhub.hide23.link/api/v1` | `WiFiClientSecure` |
| 別ドメイン + 非標準ポート | `https://myserver.com:8443/api/v1` | `WiFiClientSecure` |
| 社内 LAN（HTTP） | `http://192.168.1.100:8000/api/v1` | `WiFiClient` |
| ローカル開発 | `http://localhost:8000/api/v1` | `WiFiClient` |

```python
# Python: 環境変数 or コンストラクタ引数
export SENHUB_BASE_URL=http://192.168.1.100:8000/api/v1
s = senhub.Senhub(100, "key", base_url="http://192.168.1.100:8000/api/v1")
```

```cpp
// Arduino: begin() 第4引数 or #define
senhub.begin(100, "key", &client, "http://192.168.1.100:8000/api/v1");
```

---

## リポジトリ構成

```
senhub/
├─ arduino/
│   └─ Senhub/              Arduino（ESP32）ライブラリ
│       ├─ Senhub.h
│       ├─ Senhub.cpp
│       ├─ library.properties
│       └─ examples/
├─ python/
│   ├─ senhub/              Python ライブラリ
│   │   ├─ senhub.py
│   │   └─ __init__.py
│   ├─ test_senhub.py       Python ライブラリ テスト
│   └─ README.md
├─ server/                  FastAPI + TimescaleDB サーバー
│   ├─ main.py              FastAPI アプリ本体
│   ├─ db.py                TimescaleDB CRUD レイヤー
│   ├─ config.py            設定読み込み（.env / 環境変数）
│   ├─ schema.sql           DB初期化SQL（Hypertable・集約ビュー）
│   ├─ channels.yaml.example チャンネルキー管理テンプレート
│   ├─ .env.example         サーバー設定テンプレート
│   ├─ requirements.txt     Python 依存パッケージ
│   ├─ test_api.py          REST API エンドポイントテスト
│   └─ test_db.py           DB レイヤー直接テスト
├─ scripts/
│   ├─ gen-channel-keys.py  チャンネルキー生成スクリプト
│   ├─ make-arduino-release.sh  Arduino リリース ZIP 生成
│   └─ setup-db.sh          DB初期化スクリプト
├─ インストール.md           サーバーインストール手順（Ubuntu 24.04）
├─ senhub_ライブラリ仕様書.md ライブラリ API 仕様書
├─ senhub基本設計.md         システム基本設計書
└─ README.md
```

---

## サーバーのセットアップ

インストール手順の詳細は [`インストール.md`](インストール.md) を参照してください。

### クイックセットアップ

```bash
# 1. チャンネルキーを生成
python scripts/gen-channel-keys.py 100 "製造ライン1"
# → server/channels.yaml に追記

# 2. 設定ファイルを作成
cp server/.env.example server/.env
# .env を編集: SENHUB_DB_URL, SENHUB_DOMAIN 等を設定

# 3. DB スキーマ適用
PGPASSWORD=senhubpass psql -U senhub -d senhub -h 127.0.0.1 -f server/schema.sql

# 4. サーバー起動
python server/main.py
```

### 環境変数（主要設定）

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `SENHUB_DB_URL` | なし | TimescaleDB 接続URL（未設定でメモリモード）|
| `SENHUB_DOMAIN` | `senhub.hide23.link` | 公開ドメイン名 |
| `SENHUB_PORT` | `443`(TLS) / `8000` | リッスンポート |
| `SENHUB_USE_TLS` | `true` | HTTPS 使用: `true` / HTTP: `false` |
| `SENHUB_DEBUG` | `false` | `true` のとき `/docs` を公開（開発専用）|

---

## ライセンス

MIT
