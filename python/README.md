# Senhub Python ライブラリ

Senhub IoTシステム向け Python クライアントライブラリ。  
センサー値の送信・取得・エクスポートを Ambient と同じ感覚で操作できます。

## インストール

```bash
# GitHub から直接インストール（最新 main ブランチ）
pip install "git+https://github.com/hide23link/senhub.git#subdirectory=python"

# バージョン指定（タグ）
pip install "git+https://github.com/hide23link/senhub.git@v0.2.0#subdirectory=python"
```

## 使い方

```python
import senhub

s = senhub.Senhub(100, "your_writeKey", readKey="your_readKey")

# センサー値を送信
s.send({"d1": 23.5, "d2": 60.2})

# 機器 ON/OFF を送信
s.send({"d3": 1})   # ON
s.send({"d3": 0})   # OFF

# データ取得（最新100件）
data = s.read(n=100)

# 1分平均データ取得
data_1min = s.read(n=100, resolution="1min")

# チャンネル設定取得（readKey 必須）
prop = s.getprop()

# チャンネル設定更新
s.setprop({"d1": {"name": "温度", "unit": "℃", "type": "sensor"}})
```

## 接続先の変更

```python
# 環境変数で変更（プロセス全体に適用）
# export SENHUB_BASE_URL=http://192.168.1.100:8000/api/v1

# またはインスタンスごとに変更
s = senhub.Senhub(100, "key", base_url="http://192.168.1.100:8000/api/v1")
```

## テスト実行

```bash
cd python

# ローカルサーバーに対してテスト（要: サーバー起動済み）
python test_senhub.py

# 本番サーバーに対してテスト
SENHUB_BASE_URL=https://senhub.example.com/api/v1 python test_senhub.py
```

## 例外クラス

| 例外 | 発生条件 |
|------|---------|
| `SenhubAuthError` | writeKey / readKey 不正、または未設定 |
| `SenhubTimeoutError` | サーバー応答タイムアウト |
| `SenhubValueError` | 引数の値が不正（フィールド名・resolution・n 上限など）|
