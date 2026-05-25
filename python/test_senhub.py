#!/usr/bin/env python3
"""
Senhub Python ライブラリ サンプルテストプログラム

事前にテストサーバーを起動してください:
    cd ../server
    pip install -r requirements.txt
    uvicorn main:app --port 8000

実行方法:
    cd python
    pip install -r requirements.txt
    python test_senhub.py
"""
import sys
import time
sys.path.insert(0, ".")  # python/ ディレクトリを参照

import senhub
from senhub import SenhubAuthError, SenhubTimeoutError, SenhubValueError

# ===== テスト設定 =====
SERVER_URL  = "http://localhost:8000/api/v1"
CHANNEL_ID  = 100
WRITE_KEY   = "test_writeKey"
READ_KEY    = "test_readKey"
# ======================

OK  = "  [OK]"
NG  = "  [NG]"


def check(label: str, condition: bool):
    print(f"{'  [OK]' if condition else '  [NG]'} {label}")
    return condition


# ------------------------------------------------------------------
def test_send():
    print("\n▶ send() テスト")
    s = senhub.Senhub(CHANNEL_ID, WRITE_KEY, base_url=SERVER_URL)

    # 正常: float 値
    r = s.send({"d1": 23.5, "d2": 60.2})
    check(f"float送信 status={r}", r == 200)

    # 正常: int 値（ON/OFF）
    r = s.send({"d3": 1})
    check(f"機器ON送信 status={r}", r == 200)

    r = s.send({"d3": 0})
    check(f"機器OFF送信 status={r}", r == 200)

    # 正常: 複数フィールド
    r = s.send({"d1": 25.0, "d2": 65.0, "d4": 99, "d5": 1013.5})
    check(f"複数フィールド送信 status={r}", r == 200)

    # 異常: 不正フィールド名
    try:
        s.send({"x1": 10})
        check("不正フィールド名で例外発生", False)
    except SenhubValueError as e:
        check(f"不正フィールド名 → SenhubValueError: {e}", True)

    # 異常: writeKey 不正
    bad = senhub.Senhub(CHANNEL_ID, "wrong_key", base_url=SERVER_URL)
    try:
        bad.send({"d1": 1.0})
        check("不正 writeKey で例外発生", False)
    except SenhubAuthError as e:
        check(f"不正 writeKey → SenhubAuthError: {e}", True)


# ------------------------------------------------------------------
def test_read():
    print("\n▶ read() テスト")
    s = senhub.Senhub(CHANNEL_ID, WRITE_KEY, READ_KEY, base_url=SERVER_URL)

    # データを数件追加
    for i in range(5):
        s.send({"d1": 20.0 + i * 0.5, "d2": 50.0 + i})
        time.sleep(0.05)

    # 最新 N 件
    data = s.read(n=5)
    check(f"最新5件取得: {len(data)}件", len(data) >= 1)
    if data:
        print(f"    先頭: {data[0]}")

    # 日付指定
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    data_today = s.read(date=today)
    check(f"日付指定({today}): {len(data_today)}件", len(data_today) >= 1)

    # 異常: readKey なし
    no_rk = senhub.Senhub(CHANNEL_ID, WRITE_KEY, base_url=SERVER_URL)
    try:
        no_rk.read(n=1)
        check("readKey なしで例外発生", False)
    except SenhubAuthError as e:
        check(f"readKey なし → SenhubAuthError: {e}", True)

    # 異常: readKey 不正
    bad = senhub.Senhub(CHANNEL_ID, WRITE_KEY, "wrong_rk", base_url=SERVER_URL)
    try:
        bad.read(n=1)
        check("不正 readKey で例外発生", False)
    except SenhubAuthError as e:
        check(f"不正 readKey → SenhubAuthError: {e}", True)


# ------------------------------------------------------------------
def test_export():
    print("\n▶ export() テスト")
    s = senhub.Senhub(CHANNEL_ID, WRITE_KEY, READ_KEY, base_url=SERVER_URL)

    csv_text = s.export(format="csv")
    lines = [l for l in csv_text.strip().split("\n") if l]
    check(f"CSV エクスポート: {len(lines)}行", len(lines) >= 1)
    if lines:
        print(f"    1行目: {lines[0]}")

    json_text = s.export(format="json")
    check(f"JSON エクスポート: {len(json_text)}文字", len(json_text) > 2)


# ------------------------------------------------------------------
def test_getprop_setprop():
    print("\n▶ getprop() / setprop() テスト")
    s = senhub.Senhub(CHANNEL_ID, WRITE_KEY, READ_KEY, base_url=SERVER_URL)

    # getprop（初期状態）
    prop = s.getprop()
    check(f"getprop 取得: {list(prop.keys())}", "channelId" in prop)

    # setprop
    ok = s.setprop({
        "d1": {"name": "温度",  "unit": "℃", "type": "sensor"},
        "d2": {"name": "湿度",  "unit": "%",  "type": "sensor"},
        "d3": {"name": "機器A", "unit": "",   "type": "event"},
    })
    check(f"setprop: {'成功' if ok else '失敗'}", ok)

    # getprop（更新後）
    prop2 = s.getprop()
    check(f"d1.name = {prop2.get('d1', {}).get('name')}", prop2.get("d1", {}).get("name") == "温度")
    check(f"d3.type = {prop2.get('d3', {}).get('type')}", prop2.get("d3", {}).get("type") == "event")

    # 異常: 不正フィールド名
    try:
        s.setprop({"x1": {"name": "test", "unit": "", "type": "sensor"}})
        check("不正フィールド名で例外発生", False)
    except SenhubValueError as e:
        check(f"不正フィールド名 → SenhubValueError: {e}", True)


# ------------------------------------------------------------------
def main():
    print("=" * 50)
    print("  Senhub Python ライブラリ テスト")
    print(f"  サーバー: {SERVER_URL}")
    print(f"  チャネル: {CHANNEL_ID}")
    print("=" * 50)

    try:
        test_send()
        test_read()
        test_export()
        test_getprop_setprop()
    except ConnectionError as e:
        print(f"\n[ERROR] サーバー接続失敗: {e}")
        print("以下を確認してください:")
        print("  cd ../server && uvicorn main:app --port 8000")
        sys.exit(1)

    print("\n" + "=" * 50)
    print("  テスト完了")
    print("=" * 50)


if __name__ == "__main__":
    main()
