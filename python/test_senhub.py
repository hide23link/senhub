#!/usr/bin/env python3
"""
Senhub Python ライブラリ テストプログラム

使い方:
    # ローカルサーバー（デフォルト）
    cd python
    python test_senhub.py

    # 本番サーバーに対してテスト
    SENHUB_BASE_URL=https://senhub.hide23.link/api/v1 python test_senhub.py

    # 別サーバー
    SENHUB_BASE_URL=http://192.168.0.92:8000/api/v1 python test_senhub.py

環境変数:
    SENHUB_BASE_URL   テスト対象のサーバー URL
    TEST_CHANNEL      チャンネルID（デフォルト: 100）
    WRITE_KEY         書き込みキー（デフォルト: test_writeKey）
    READ_KEY          読み取りキー（デフォルト: test_readKey）

ローカルサーバー起動方法:
    cd ../server
    SENHUB_USE_TLS=false SENHUB_PORT=8000 python main.py
"""
import os
import sys
import time
sys.path.insert(0, ".")  # python/ ディレクトリを参照

import senhub
from senhub import SenhubAuthError, SenhubTimeoutError, SenhubValueError

# ===== テスト設定（環境変数で上書き可能）=====
SERVER_URL  = os.environ.get("SENHUB_BASE_URL", "http://localhost:8000/api/v1")
CHANNEL_ID  = int(os.environ.get("TEST_CHANNEL", "100"))
WRITE_KEY   = os.environ.get("WRITE_KEY",        "test_writeKey")
READ_KEY    = os.environ.get("READ_KEY",         "test_readKey")
# ============================================

_pass = _fail = 0


def check(label: str, condition: bool):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  ✅ PASS  {label}")
    else:
        _fail += 1
        print(f"  ❌ FAIL  {label}")
    return condition


def header(title: str):
    print(f"\n{'─'*54}")
    print(f"  {title}")
    print(f"{'─'*54}")


# ------------------------------------------------------------------
def test_send():
    header("1. send() テスト")
    s = senhub.Senhub(CHANNEL_ID, WRITE_KEY, base_url=SERVER_URL)

    # 正常: float 値
    r = s.send({"d1": 23.5, "d2": 60.2})
    check(f"float送信 → 200: {r}", r == 200)

    # 正常: int 値（ON/OFF）
    r = s.send({"d3": 1})
    check(f"機器ON送信 → 200: {r}", r == 200)

    r = s.send({"d3": 0})
    check(f"機器OFF送信 → 200: {r}", r == 200)

    # 正常: 複数フィールド
    r = s.send({"d1": 25.0, "d2": 65.0, "d4": 99, "d5": 1013.5})
    check(f"複数フィールド送信 → 200: {r}", r == 200)

    # 異常: 不正フィールド名
    try:
        s.send({"x1": 10})
        check("不正フィールド名 → SenhubValueError", False)
    except SenhubValueError as e:
        check(f"不正フィールド名 → SenhubValueError: {e}", True)

    # 異常: writeKey 不正
    bad = senhub.Senhub(CHANNEL_ID, "wrong_key", base_url=SERVER_URL)
    try:
        bad.send({"d1": 1.0})
        check("不正 writeKey → SenhubAuthError", False)
    except SenhubAuthError as e:
        check(f"不正 writeKey → SenhubAuthError: {e}", True)


# ------------------------------------------------------------------
def test_read():
    header("2. read() テスト")
    s = senhub.Senhub(CHANNEL_ID, WRITE_KEY, READ_KEY, base_url=SERVER_URL)

    # データを数件追加
    for i in range(5):
        s.send({"d1": 20.0 + i * 0.5, "d2": 50.0 + i})
        time.sleep(0.05)

    # 最新 N 件
    data = s.read(n=5)
    check(f"最新5件取得: {len(data)}件", len(data) >= 1)
    if data:
        print(f"      先頭: {data[0]}")

    # 日付指定
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    data_today = s.read(date=today)
    check(f"日付指定({today}): {len(data_today)}件", len(data_today) >= 1)

    # resolution 指定
    data_1min = s.read(n=5, resolution="1min")
    check(f"resolution='1min' で取得", isinstance(data_1min, list))

    # 異常: readKey なし
    no_rk = senhub.Senhub(CHANNEL_ID, WRITE_KEY, base_url=SERVER_URL)
    try:
        no_rk.read(n=1)
        check("readKey なし → SenhubAuthError", False)
    except SenhubAuthError as e:
        check(f"readKey なし → SenhubAuthError: {e}", True)

    # 異常: readKey 不正
    bad = senhub.Senhub(CHANNEL_ID, WRITE_KEY, "wrong_rk", base_url=SERVER_URL)
    try:
        bad.read(n=1)
        check("不正 readKey → SenhubAuthError", False)
    except SenhubAuthError as e:
        check(f"不正 readKey → SenhubAuthError: {e}", True)

    # 異常: n 上限超え
    try:
        s.read(n=senhub.MAX_N + 1)
        check(f"n={senhub.MAX_N + 1} → SenhubValueError", False)
    except SenhubValueError as e:
        check(f"n 上限超え → SenhubValueError: {e}", True)

    # 異常: resolution 不正値
    try:
        s.read(resolution="invalid")
        check("resolution='invalid' → SenhubValueError", False)
    except SenhubValueError as e:
        check(f"不正 resolution → SenhubValueError: {e}", True)


# ------------------------------------------------------------------
def test_export():
    header("3. export() テスト")
    s = senhub.Senhub(CHANNEL_ID, WRITE_KEY, READ_KEY, base_url=SERVER_URL)

    csv_text = s.export(format="csv")
    lines = [l for l in csv_text.strip().split("\n") if l]
    check(f"CSV エクスポート: {len(lines)}行", len(lines) >= 1)
    if lines:
        print(f"      1行目: {lines[0]}")

    json_text = s.export(format="json")
    check(f"JSON エクスポート: {len(json_text)}文字", len(json_text) > 2)

    # 異常: readKey なし
    no_rk = senhub.Senhub(CHANNEL_ID, WRITE_KEY, base_url=SERVER_URL)
    try:
        no_rk.export()
        check("readKey なし → SenhubAuthError", False)
    except SenhubAuthError as e:
        check(f"readKey なし → SenhubAuthError: {e}", True)


# ------------------------------------------------------------------
def test_getprop_setprop():
    header("4. getprop() / setprop() テスト")
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

    # 異常: getprop に readKey なし
    no_rk = senhub.Senhub(CHANNEL_ID, WRITE_KEY, base_url=SERVER_URL)
    try:
        no_rk.getprop()
        check("getprop readKey なし → SenhubAuthError", False)
    except SenhubAuthError as e:
        check(f"getprop readKey なし → SenhubAuthError: {e}", True)

    # 異常: getprop に不正 readKey
    bad_rk = senhub.Senhub(CHANNEL_ID, WRITE_KEY, "wrong_rk", base_url=SERVER_URL)
    try:
        bad_rk.getprop()
        check("getprop 不正 readKey → SenhubAuthError", False)
    except SenhubAuthError as e:
        check(f"getprop 不正 readKey → SenhubAuthError: {e}", True)

    # 異常: setprop に不正フィールド名
    try:
        s.setprop({"x1": {"name": "test", "unit": "", "type": "sensor"}})
        check("不正フィールド名 → SenhubValueError", False)
    except SenhubValueError as e:
        check(f"不正フィールド名 → SenhubValueError: {e}", True)

    # 異常: setprop に不正 writeKey
    bad_wk = senhub.Senhub(CHANNEL_ID, "wrong_wk", READ_KEY, base_url=SERVER_URL)
    try:
        bad_wk.setprop({"d1": {"name": "x", "unit": "", "type": "sensor"}})
        check("setprop 不正 writeKey → SenhubAuthError", False)
    except SenhubAuthError as e:
        check(f"setprop 不正 writeKey → SenhubAuthError: {e}", True)


# ------------------------------------------------------------------
def main():
    print("=" * 54)
    print("  Senhub Python ライブラリ テスト")
    print(f"  サーバー: {SERVER_URL}")
    print(f"  チャンネル: {CHANNEL_ID}")
    print(f"  WRITE_KEY : {WRITE_KEY}")
    print(f"  READ_KEY  : {READ_KEY}")
    print("=" * 54)

    try:
        test_send()
        test_read()
        test_export()
        test_getprop_setprop()
    except ConnectionError as e:
        print(f"\n[ERROR] サーバー接続失敗: {e}")
        print("以下を確認してください:")
        print("  cd ../server && SENHUB_USE_TLS=false SENHUB_PORT=8000 python main.py")
        print("または:")
        print("  SENHUB_BASE_URL=https://senhub.hide23.link/api/v1 python test_senhub.py")
        sys.exit(1)

    print()
    print("=" * 54)
    total = _pass + _fail
    if _fail == 0:
        print(f"  🎉 全テスト PASS！  {_pass}/{total} 件")
    else:
        print(f"  ⚠️  {_fail} 件失敗    {_pass}/{total} 件")
    print("=" * 54)

    sys.exit(1 if _fail > 0 else 0)


if __name__ == "__main__":
    main()
