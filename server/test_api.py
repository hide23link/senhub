"""
Senhub API 全体テストプログラム

senhub.hide23.link（または任意のサーバー）に対して
全エンドポイントの動作を HTTP レベルで検証する。

テスト項目:
    1. 認証テスト（正常・不正キー・未定義チャンネル）
    2. センサーデータ 単発書き込み・読み出し
    3. センサーデータ バッチ書き込み（POST /dataarray）
    4. ON/OFF イベント送受信
    5. プロパティ 更新・取得
    6. データエクスポート（CSV / JSON）
    7. Web画面向けエンドポイント（/state / /events / /uptime）
    8. フィルタリング（n件・start/end・date）
    9. 連続送信テスト（10件連続書き込み → 読み出し一致確認）

使い方:
    # デフォルト（senhub.hide23.link）
    python test_api.py

    # 別のサーバーを指定
    BASE_URL=http://192.168.0.92:8000/api/v1 python test_api.py

環境変数:
    BASE_URL        APIベースURL（デフォルト: https://senhub.hide23.link/api/v1）
    TEST_CHANNEL    テスト用チャンネルID（デフォルト: 100）
    WRITE_KEY       テスト用WRITEキー（デフォルト: test_writeKey）
    READ_KEY        テスト用READキー（デフォルト: test_readKey）
"""
import os
import sys
import time
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta

# ─────────────────────────────────────────
# 設定
# ─────────────────────────────────────────
BASE_URL    = os.environ.get("BASE_URL",      "https://senhub.hide23.link/api/v1")
CH          = int(os.environ.get("TEST_CHANNEL", "100"))
WRITE_KEY   = os.environ.get("WRITE_KEY",    "test_writeKey")
READ_KEY    = os.environ.get("READ_KEY",     "test_readKey")
WRONG_KEY   = "wrong_key_12345"
UNKNOWN_CH  = 9999   # channels.yaml に未定義のチャンネル

# ─────────────────────────────────────────
# テストフレームワーク（urllib のみ・外部依存なし）
# ─────────────────────────────────────────
_pass = _fail = 0

def header(title: str):
    print()
    print("─" * 62)
    print(f"  {title}")
    print("─" * 62)

def ok(msg: str):
    global _pass
    _pass += 1
    print(f"  ✅ PASS  {msg}")

def ng(msg: str, detail: str = ""):
    global _fail
    _fail += 1
    print(f"  ❌ FAIL  {msg}")
    if detail:
        print(f"           {detail}")

def check(cond: bool, msg: str, detail: str = ""):
    if cond:
        ok(msg)
    else:
        ng(msg, detail)

def get(path: str, params: dict = None) -> tuple[int, str]:
    """GET リクエストを送信して (status_code, body) を返す"""
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    try:
        with urllib.request.urlopen(url, timeout=10) as res:
            return res.status, res.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
    except Exception as e:
        return 0, str(e)

def post(path: str, body: str, params: dict = None) -> tuple[int, str]:
    """POST リクエストを送信して (status_code, body) を返す"""
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = body.encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, res.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
    except Exception as e:
        return 0, str(e)

def csv_rows(body: str) -> list[list[str]]:
    """CSV レスポンス（ヘッダー行あり）をパース"""
    lines = body.strip().split("\n")
    return [line.split(",") for line in lines[1:] if line.strip()]

# ─────────────────────────────────────────
# テスト実装
# ─────────────────────────────────────────

def test_auth():
    header("1. 認証テスト")

    # 正しい WRITE KEY
    s, b = get(f"/channels/{CH}/data", {"writeKey": WRITE_KEY, "d1": "1.0"})
    check(s == 200, f"正しい writeKey → 200: {b.strip()}")

    # 不正な WRITE KEY
    s, b = get(f"/channels/{CH}/data", {"writeKey": WRONG_KEY, "d1": "1.0"})
    check(s == 401, f"不正な writeKey → 401: {b.strip()}")

    # 正しい READ KEY
    s, b = get(f"/channels/{CH}/data", {"readKey": READ_KEY})
    check(s == 200, f"正しい readKey → 200")

    # 不正な READ KEY
    s, b = get(f"/channels/{CH}/data", {"readKey": WRONG_KEY})
    check(s == 401, f"不正な readKey → 401: {b.strip()}")

    # キーなしリクエスト
    s, b = get(f"/channels/{CH}/data")
    check(s == 400, f"キーなし → 400: {b.strip()}")

    # 未定義チャンネル（セキュリティモード）
    s, b = get(f"/channels/{UNKNOWN_CH}/data", {"writeKey": WRITE_KEY})
    check(s == 404, f"未定義チャンネル(ch{UNKNOWN_CH}) → 404: {b.strip()}")


def test_sensor_single():
    header("2. センサーデータ 単発書き込み・読み出し")

    # 書き込み（d1〜d4 に値を設定）
    s, b = get(f"/channels/{CH}/data", {
        "writeKey": WRITE_KEY,
        "d1": "23.5", "d2": "61.0", "d3": "1013.0", "d4": "0.5"
    })
    check(s == 200, f"d1〜d4 書き込み → 200")
    time.sleep(0.5)

    # 読み出し・ヘッダー確認
    s, b = get(f"/channels/{CH}/data", {"readKey": READ_KEY, "n": "1"})
    check(s == 200, "読み出し → 200")
    check(b.startswith("created,d1,d2,d3,d4,d5,d6,d7,d8"), f"CSVヘッダー確認")

    rows = csv_rows(b)
    check(len(rows) == 1, f"n=1 で1件取得: {len(rows)}件")
    if rows:
        check(rows[0][1] == "23.5", f"d1=23.5 が正確に返る: {rows[0][1]}")
        check(rows[0][2] == "61.0",  f"d2=61.0 が正確に返る: {rows[0][2]}")
        check(rows[0][5] == "",      f"d5（未設定）が空文字: '{rows[0][5]}'")


def test_sensor_batch():
    header("3. センサーデータ バッチ書き込み (POST /dataarray)")

    now = int(time.time())
    # フォーマット: writeKey=...\nts,d1,d2,...
    lines = [f"writeKey={WRITE_KEY}"]
    values = []
    for i in range(5):
        ts = now - (4 - i) * 10   # 10秒間隔
        d1 = round(20.0 + i * 0.5, 1)
        d2 = round(50.0 + i * 1.0, 1)
        lines.append(f"{ts},{d1},{d2},,,,,,")
        values.append((d1, d2))

    body = "\n".join(lines)
    s, b = post(f"/channels/{CH}/dataarray", body)
    check(s == 200, f"バッチ送信(5件) → 200: {b.strip()}")
    check("count=5" in b, f"count=5 が返る: {b.strip()}")
    time.sleep(0.5)

    # 読み出して件数・値を確認（他テストのデータが混在する可能性があるため集合で比較）
    s, b = get(f"/channels/{CH}/data", {"readKey": READ_KEY, "n": "5"})
    rows = csv_rows(b)
    check(len(rows) == 5, f"n=5 で5件取得: {len(rows)}件")
    if len(rows) == 5:
        got_d1 = {row[1] for row in rows if row[1]}
        sent_d1 = {str(v[0]) for v in values}
        overlap = len(got_d1 & sent_d1)
        check(overlap >= 3, f"バッチ送信値が結果に含まれる ({overlap}/5件一致)")


def test_events():
    header("4. ON/OFF イベント (POST /event)")

    now = int(time.time())
    on_ts  = now - 300   # 5分前に ON
    off_ts = now - 60    # 1分前に OFF（継続 4分=240秒）

    # ON イベント送信
    body_on = f"writeKey={WRITE_KEY}\n{on_ts},3,1"
    s, b = post(f"/channels/{CH}/event", body_on)
    check(s == 200, f"ONイベント送信 → 200: {b.strip()}")

    # OFF イベント送信
    body_off = f"writeKey={WRITE_KEY}\n{off_ts},3,0"
    s, b = post(f"/channels/{CH}/event", body_off)
    check(s == 200, f"OFFイベント送信 → 200: {b.strip()}")

    # 不正キーでのイベント送信
    body_ng = f"writeKey={WRONG_KEY}\n{now},3,1"
    s, b = post(f"/channels/{CH}/event", body_ng)
    check(s == 401, f"不正キーでのイベント → 401")

    # イベント履歴取得（直近10件からON/OFFの両方を確認）
    s, b = get(f"/channels/{CH}/events", {"readKey": READ_KEY, "n": "10"})
    check(s == 200, f"GET /events → 200")
    rows = [r.split(",") for r in b.strip().split("\n") if r.strip()]
    check(len(rows) >= 2, f"イベント2件以上取得: {len(rows)}件")
    if len(rows) >= 2:
        states = {r[2] for r in rows if len(r) >= 3}
        check("1" in states and "0" in states, f"ON(1)とOFF(0)が両方存在: {sorted(states)}")

    # 現在の稼働状態
    s, b = get(f"/channels/{CH}/state", {"readKey": READ_KEY})
    check(s == 200, f"GET /state → 200")
    check(len(b.strip()) > 0, f"状態データが返る: {b.strip()[:50]}")


def test_properties():
    header("5. プロパティ 更新・取得")

    # プロパティ更新
    body = "\n".join([
        "d1.name=温度",
        "d1.unit=℃",
        "d1.type=sensor",
        "d2.name=湿度",
        "d2.unit=%",
        "d3.name=気圧",
        "d3.unit=hPa",
    ])
    s, b = post(f"/channels/{CH}/properties", body, {"writeKey": WRITE_KEY})
    check(s == 200, f"プロパティ更新 → 200: {b.strip()}")

    # プロパティ取得
    s, b = get(f"/channels/{CH}/properties", {"readKey": READ_KEY})
    check(s == 200, f"プロパティ取得 → 200")
    check("d1.name=温度" in b, f"d1.name=温度: {'OK' if 'd1.name=温度' in b else b[:80]}")
    check("d1.unit=℃"   in b, f"d1.unit=℃: {'OK' if 'd1.unit=℃' in b else b[:80]}")
    check("d2.name=湿度" in b, f"d2.name=湿度: {'OK' if 'd2.name=湿度' in b else b[:80]}")
    check(f"channelId={CH}" in b, f"channelId={CH}")

    # 不正キーでの更新
    s, b = post(f"/channels/{CH}/properties", body, {"writeKey": WRONG_KEY})
    check(s == 401, f"不正キーでのプロパティ更新 → 401")


def test_export():
    header("6. データエクスポート (GET /export)")

    # CSV 形式
    s, b = get(f"/channels/{CH}/export", {"readKey": READ_KEY, "format": "csv"})
    check(s == 200, f"CSV エクスポート → 200")
    check(b.startswith("created,d1"), f"CSV ヘッダー確認")
    rows = csv_rows(b)
    check(len(rows) > 0, f"CSV データあり: {len(rows)}件")

    # JSON 形式
    s, b = get(f"/channels/{CH}/export", {"readKey": READ_KEY, "format": "json"})
    check(s == 200, f"JSON エクスポート → 200")
    try:
        data = json.loads(b)
        check(isinstance(data, list), f"JSON が配列: {len(data)}件")
        if data:
            check("created" in data[0], f"JSON に 'created' キーあり")
            check("d1"      in data[0], f"JSON に 'd1' キーあり")
    except json.JSONDecodeError as e:
        ng("JSON パース失敗", str(e))

    # start/end フィルタ付きエクスポート
    start = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    end   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s, b = get(f"/channels/{CH}/export", {
        "readKey": READ_KEY, "format": "csv", "start": start, "end": end
    })
    check(s == 200, f"start/end フィルタ付きエクスポート → 200")


def test_filter():
    header("7. フィルタリング（n件・start/end・date）")

    # n=3 件取得
    s, b = get(f"/channels/{CH}/data", {"readKey": READ_KEY, "n": "3"})
    rows = csv_rows(b)
    check(s == 200 and len(rows) == 3, f"n=3 で3件: {len(rows)}件")

    # n=1 件取得（最新1件）
    s, b = get(f"/channels/{CH}/data", {"readKey": READ_KEY, "n": "1"})
    rows = csv_rows(b)
    check(s == 200 and len(rows) == 1, f"n=1 で1件: {len(rows)}件")

    # start/end フィルタ
    start = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    end   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s, b = get(f"/channels/{CH}/data", {"readKey": READ_KEY, "start": start, "end": end})
    rows = csv_rows(b)
    check(s == 200, f"start/end フィルタ → 200")
    check(len(rows) > 0, f"start/end フィルタで {len(rows)}件取得")

    # date フィルタ（今日の日付）
    today = datetime.now().strftime("%Y-%m-%d")
    s, b = get(f"/channels/{CH}/data", {"readKey": READ_KEY, "date": today})
    check(s == 200, f"date={today} フィルタ → 200")

    # 未来の日付（0件になるはず）
    future = "2099-01-01"
    s, b = get(f"/channels/{CH}/data", {"readKey": READ_KEY, "date": future})
    rows = csv_rows(b)
    check(s == 200 and len(rows) == 0, f"未来の date → 0件: {len(rows)}件")


def test_uptime():
    header("8. 稼働時間・稼働率 (GET /uptime)")

    start = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    end   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    s, b = get(f"/channels/{CH}/uptime", {
        "readKey": READ_KEY, "field": "3", "start": start, "end": end
    })
    check(s == 200, f"GET /uptime → 200")
    parts = b.strip().split(",")
    check(len(parts) == 3, f"レスポンスが3フィールド(on_sec,total_sec,rate): {b.strip()}")
    if len(parts) == 3:
        try:
            on_sec    = int(parts[0])
            total_sec = int(parts[1])
            rate      = float(parts[2])
            check(total_sec == 3600, f"total_seconds=3600: {total_sec}")
            check(0 <= rate <= 100,  f"rate が 0〜100%%: {rate}%%")
            check(on_sec >= 0,       f"on_seconds >= 0: {on_sec}秒")
        except ValueError as e:
            ng("数値パース失敗", str(e))


def test_continuous():
    header("9. 連続送信テスト（10件 書き込み → 読み出し一致確認）")

    # 10件のデータを1秒以内に連続送信
    sent = []
    for i in range(10):
        d1 = round(10.0 + i * 0.1, 1)
        d2 = round(40.0 + i * 0.2, 1)
        s, b = get(f"/channels/{CH}/data", {
            "writeKey": WRITE_KEY, "d1": str(d1), "d2": str(d2)
        })
        if s == 200:
            sent.append((d1, d2))
        else:
            ng(f"連続送信 {i+1}件目 失敗: status={s}")
    check(len(sent) == 10, f"10件全て送信成功: {len(sent)}件")

    time.sleep(1)

    # 最新10件を読み出して末尾10件と照合
    s, b = get(f"/channels/{CH}/data", {"readKey": READ_KEY, "n": "10"})
    rows = csv_rows(b)
    check(len(rows) == 10, f"最新10件取得: {len(rows)}件")

    if len(rows) == 10 and len(sent) == 10:
        match = sum(1 for i, row in enumerate(rows) if row[1] == str(sent[i][0]))
        check(match == 10, f"送信値と受信値が完全一致: {match}/10件")


def test_debug():
    header("10. デバッグエンドポイント (GET /debug)")

    s, b = get(f"/channels/{CH}/debug")
    check(s == 200, f"GET /debug → 200")
    try:
        data = json.loads(b)
        check("channel_id"   in data, f"'channel_id' キーあり: {data.get('channel_id')}")
        check("mode"         in data, f"'mode' キーあり: {data.get('mode')}")
        check("properties"   in data, f"'properties' キーあり")
        check(data.get("mode") == "db", f"DB モードで動作中: {data.get('mode')}")
    except json.JSONDecodeError as e:
        ng("JSON パース失敗", str(e))


# ─────────────────────────────────────────
# メイン
# ─────────────────────────────────────────
def main():
    print("=" * 62)
    print("  Senhub API 全体テスト")
    print(f"  BASE_URL  : {BASE_URL}")
    print(f"  チャンネル: ch{CH}")
    print(f"  WRITE_KEY : {WRITE_KEY}")
    print(f"  READ_KEY  : {READ_KEY}")
    print("=" * 62)

    # サーバー疎通確認
    s, b = get(f"/channels/{CH}/debug")
    if s == 0:
        print(f"\n❌ サーバーに接続できません: {b}")
        print(f"   BASE_URL={BASE_URL} を確認してください")
        sys.exit(1)

    start_time = time.time()

    test_auth()
    test_sensor_single()
    test_sensor_batch()
    test_events()
    test_properties()
    test_export()
    test_filter()
    test_uptime()
    test_continuous()
    test_debug()

    elapsed = round(time.time() - start_time, 1)

    print()
    print("=" * 62)
    total = _pass + _fail
    if _fail == 0:
        print(f"  🎉 全テスト PASS！  {_pass}/{total} 件  ({elapsed}秒)")
    else:
        print(f"  ⚠️  {_fail} 件失敗    {_pass}/{total} 件  ({elapsed}秒)")
    print("=" * 62)
    print()
    sys.exit(0 if _fail == 0 else 1)


if __name__ == "__main__":
    main()
