# Senhub

工場用IoTシステム向けライブラリ。センサー値（連続データ）と機器のON/OFF状態（イベントデータ）を ESP32 から Senhub サーバーに送信します。

- **デフォルトエンドポイント**: `https://senhub.hide.link`（変更可）
- **Ambientと同じ操作感**: `begin` / `set` / `send`

---

## インストール

### Python ライブラリ

```bash
pip install "git+https://github.com/hide23link/senhub.git#subdirectory=python"
```

バージョン指定:

```bash
pip install "git+https://github.com/hide23link/senhub.git@v0.1.2#subdirectory=python"
```

### Arduino（ESP32）ライブラリ

**方法①: GitHub Releases からZIPをダウンロード（推奨）**

1. [Releases](https://github.com/hide23link/senhub/releases) から `Senhub-x.x.x.zip` をダウンロード
2. Arduino IDE: スケッチ → ライブラリをインクルード → .ZIP形式のライブラリをインストール → ZIPを選択

**方法②: Git clone（開発・最新版）**

```bash
cd ~/Documents/Arduino/libraries
git clone https://github.com/hide23link/senhub.git senhub-repo
# Arduino IDE のライブラリパスに Senhub フォルダが認識される:
#   ~/Documents/Arduino/libraries/senhub-repo/arduino/Senhub/
```

> Arduino IDE 2.x はサブディレクトリの `library.properties` を自動検出します。

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
| 本番 HTTPS | `https://senhub.hide.link/api/v1` | `WiFiClientSecure` |
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
│   └─ Senhub/          Arduino（ESP32）ライブラリ
│       ├─ Senhub.h
│       ├─ Senhub.cpp
│       ├─ library.properties
│       └─ examples/
├─ python/
│   └─ senhub/          Python ライブラリ
│       ├─ senhub.py
│       └─ __init__.py
├─ server/              FastAPI テストサーバー（開発用）
├─ scripts/
│   └─ make-arduino-release.sh  Arduino リリース ZIP 生成
└─ README.md
```

---

## ライセンス

MIT
