"""
Senhub DB 接続テストプログラム

TimescaleDB に直接接続して以下を確認する:
    1. DB接続・チャンネル登録
    2. WRITE KEY の確認（正しいキーと不正なキーの両方）
    3. センサーデータの書き込みと読み出し
    4. バッチデータ（POST /dataarray 相当）の書き込みと読み出し
    5. ON/OFFイベントの書き込み・duration 計算・読み出し
    6. プロパティ（name/unit/type）の書き込みと読み出し
    7. 稼働時間・稼働率の計算

使い方:
    # DB接続URLを指定して実行
    SENHUB_DB_URL=postgresql://senhub:senhubpass@localhost:5432/senhub python test_db.py

    # または .env に設定してから実行
    python test_db.py

環境変数:
    SENHUB_DB_URL  : TimescaleDB接続URL（必須）
    TEST_CHANNEL   : テスト用チャンネルID（デフォルト: 999）
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta

# server/ ディレクトリを sys.path に追加（直接実行時）
sys.path.insert(0, os.path.dirname(__file__))

import config

# DB URLが設定されているか確認
if not config.USE_DB:
    print("=" * 60)
    print("❌ エラー: SENHUB_DB_URL が設定されていません")
    print()
    print("以下の方法で設定してください:")
    print("  export SENHUB_DB_URL=postgresql://senhub:senhubpass@localhost:5432/senhub")
    print("  python test_db.py")
    print()
    print("または server/.env に追記:")
    print("  SENHUB_DB_URL=postgresql://senhub:senhubpass@localhost:5432/senhub")
    print("=" * 60)
    sys.exit(1)

import db

# テスト用チャンネルID（本番チャンネルと干渉しないよう大きな値を使う）
TEST_CHANNEL_ID = int(os.environ.get("TEST_CHANNEL", "999"))

PASS = "✅ PASS"
FAIL = "❌ FAIL"


def header(title: str):
    print()
    print("─" * 60)
    print(f"  {title}")
    print("─" * 60)


def result(ok: bool, msg: str):
    print(f"  {PASS if ok else FAIL}  {msg}")
    if not ok:
        # テスト失敗をカウント（グローバル変数）
        global _fail_count
        _fail_count += 1


_fail_count = 0


async def cleanup(conn):
    """テスト用チャンネルのデータを全削除"""
    await conn.execute("DELETE FROM sensor_data WHERE channel_id = $1", TEST_CHANNEL_ID)
    await conn.execute("DELETE FROM events WHERE channel_id = $1", TEST_CHANNEL_ID)
    await conn.execute("DELETE FROM channel_properties WHERE channel_id = $1", TEST_CHANNEL_ID)
    await conn.execute("DELETE FROM channels WHERE channel_id = $1", TEST_CHANNEL_ID)


async def run_tests():
    print("=" * 60)
    print(f"  Senhub DB 接続テスト")
    print(f"  DB URL : {config.DB_URL.replace(config.DB_URL.split('@')[0].split('//')[-1].split(':')[-1], '****') if '@' in config.DB_URL else config.DB_URL}")
    print(f"  チャンネル : ch{TEST_CHANNEL_ID}")
    print("=" * 60)

    # ──────────────────────────────────
    # 0. DB接続テスト
    # ──────────────────────────────────
    header("0. DB接続")
    try:
        await db.init_pool()
        result(True, "コネクションプール初期化成功")
    except Exception as e:
        result(False, f"DB接続失敗: {e}")
        print()
        print("  ヒント: PostgreSQL が起動しているか確認してください")
        print("    sudo service postgresql start")
        print("    sudo -u postgres bash scripts/setup-db.sh")
        return

    pool = db._pool_ok()
    async with pool.acquire() as conn:
        # テスト開始前にクリーンアップ
        await cleanup(conn)
        result(True, f"ch{TEST_CHANNEL_ID} の既存テストデータを削除")

    # ──────────────────────────────────
    # 1. チャンネル登録
    # ──────────────────────────────────
    header("1. チャンネル登録")

    ch = await db.get_or_create_channel(TEST_CHANNEL_ID)
    result(ch is not None, "get_or_create_channel() が None でない")
    if ch:
        result(ch["channel_id"] == TEST_CHANNEL_ID, f"channel_id = {ch['channel_id']}")
        result("write_key" in ch, f"write_key = {ch['write_key']}")
        result("read_key" in ch, f"read_key  = {ch['read_key']}")

    # 2回目呼び出しで同じ結果を返すか
    ch2 = await db.get_or_create_channel(TEST_CHANNEL_ID)
    result(
        ch2 is not None and ch2["write_key"] == ch["write_key"],
        "2回目呼び出しで同じ write_key が返される（冪等性）"
    )

    # channel_properties が d1〜d8 で初期化されているか
    props = await db.get_properties(TEST_CHANNEL_ID)
    result(len(props) == 8, f"channel_properties に d1〜d8 が登録 ({len(props)} 件)")
    result(all(f"d{i}" in props for i in range(1, 9)), "d1〜d8 すべて存在")

    # ──────────────────────────────────
    # 2. WRITE KEY の確認
    # ──────────────────────────────────
    header("2. WRITE KEY の確認")

    write_key = ch["write_key"]
    read_key  = ch["read_key"]

    result(len(write_key) > 0, f"write_key が空でない: '{write_key}'")
    result(len(read_key) > 0,  f"read_key が空でない: '{read_key}'")
    result(write_key != read_key, "write_key と read_key が異なる")

    # channels.yaml のキーと一致するか確認
    ch_cfg = config.CHANNELS.get(TEST_CHANNEL_ID)
    if ch_cfg:
        result(
            write_key == ch_cfg["write_key"],
            f"channels.yaml の write_key と一致: {write_key}"
        )
    else:
        result(True, f"channels.yaml に ch{TEST_CHANNEL_ID} の定義なし → デフォルトキーを使用")

    # ──────────────────────────────────
    # 3. センサーデータの書き込みと読み出し
    # ──────────────────────────────────
    header("3. センサーデータ（単発書き込み）")

    # 3件のセンサーデータを1秒間隔で書き込む
    base_time = datetime.now() - timedelta(seconds=10)
    test_rows = [
        {"ts": base_time,                         "d1": 25.5, "d2": 60.0},
        {"ts": base_time + timedelta(seconds=3),  "d1": 26.0, "d2": 61.5, "d3": 1.0},
        {"ts": base_time + timedelta(seconds=6),  "d1": 24.8, "d2": 59.0},
    ]

    for i, row in enumerate(test_rows, 1):
        try:
            await db.insert_sensor_row(
                TEST_CHANNEL_ID, row["ts"],
                d1=row.get("d1"), d2=row.get("d2"), d3=row.get("d3"),
            )
            result(True, f"  行{i} INSERT成功: d1={row.get('d1')}, d2={row.get('d2')}")
        except Exception as e:
            result(False, f"  行{i} INSERT失敗: {e}")

    # 読み出し
    data = await db.query_sensor_data(TEST_CHANNEL_ID)
    result(len(data) == 3, f"query_sensor_data() → {len(data)} 件（期待: 3件）")
    if data:
        result("created" in data[0], f"'created' キーが存在: {data[0]['created']}")
        result(data[0]["d1"] == 25.5, f"d1 の値が正確: {data[0]['d1']}")
        result(data[1]["d3"] == 1.0,  f"d3 の値が正確: {data[1]['d3']}")
        result(data[2]["d3"] is None, f"d3 が None（未設定フィールド）: {data[2]['d3']}")

    # n=2 で最新2件取得
    data_n2 = await db.query_sensor_data(TEST_CHANNEL_ID, n=2)
    result(len(data_n2) == 2, f"n=2 で2件取得: {len(data_n2)} 件")

    # ──────────────────────────────────
    # 4. バッチ書き込み
    # ──────────────────────────────────
    header("4. センサーデータ（バッチ書き込み）")

    batch_base = datetime.now() - timedelta(seconds=5)
    batch_rows = [
        {"ts": batch_base,                        "d1": "30.0", "d2": "70.0"},
        {"ts": batch_base + timedelta(seconds=1), "d1": "31.5", "d2": None},
        {"ts": batch_base + timedelta(seconds=2), "d1": "",     "d2": "72.0"},
    ]

    try:
        count = await db.insert_sensor_rows(TEST_CHANNEL_ID, batch_rows)
        result(count == 3, f"insert_sensor_rows() → {count} 件INSERT（期待: 3件）")
    except Exception as e:
        result(False, f"バッチINSERT失敗: {e}")

    data_all = await db.query_sensor_data(TEST_CHANNEL_ID)
    result(len(data_all) == 6, f"合計 6 件になった: {len(data_all)} 件")

    # ──────────────────────────────────
    # 5. ON/OFFイベント
    # ──────────────────────────────────
    header("5. ON/OFFイベント（書き込み・duration計算）")

    now = datetime.now()
    on_time  = now - timedelta(minutes=5)   # 5分前にON
    off_time = now - timedelta(minutes=2)   # 2分前にOFF（継続3分=180秒）

    # ON イベント
    try:
        await db.insert_event(TEST_CHANNEL_ID, on_time, field=3, state=1)
        result(True, f"ONイベント INSERT: field=3, time={on_time.strftime('%H:%M:%S')}")
    except Exception as e:
        result(False, f"ONイベント INSERT失敗: {e}")

    # OFF イベント（duration が計算されるはず）
    try:
        await db.insert_event(TEST_CHANNEL_ID, off_time, field=3, state=0)
        result(True, f"OFFイベント INSERT: field=3, time={off_time.strftime('%H:%M:%S')}")
    except Exception as e:
        result(False, f"OFFイベント INSERT失敗: {e}")

    # events テーブルを直接確認
    pool = db._pool_ok()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT time, field, state, duration FROM events "
            "WHERE channel_id=$1 ORDER BY time ASC",
            TEST_CHANNEL_ID
        )

    result(len(rows) == 2, f"eventsテーブルに2件: {len(rows)} 件")
    if len(rows) >= 2:
        on_row  = rows[0]
        off_row = rows[1]
        result(on_row["state"] == 1,   f"1件目: state=1 (ON)")
        result(on_row["duration"] is None, f"ONイベント: duration=NULL（期待）: {on_row['duration']}")
        result(off_row["state"] == 0,  f"2件目: state=0 (OFF)")
        # duration の期待値: 3分 = 180秒（多少の誤差を許容）
        dur = off_row["duration"]
        result(
            dur is not None and 175 <= dur <= 185,
            f"OFFイベント: duration={dur}秒（期待: ~180秒）"
        )

    # ──────────────────────────────────
    # 6. プロパティ
    # ──────────────────────────────────
    header("6. プロパティ（書き込み・読み出し）")

    updates = {
        "d1": {"name": "温度", "unit": "℃", "type": "sensor"},
        "d2": {"name": "湿度", "unit": "%",  "type": "sensor"},
        "d3": {"name": "ポンプ", "unit": "",   "type": "event"},
    }

    try:
        await db.set_properties(TEST_CHANNEL_ID, updates)
        result(True, "set_properties() 成功")
    except Exception as e:
        result(False, f"set_properties() 失敗: {e}")

    props = await db.get_properties(TEST_CHANNEL_ID)
    result(props.get("d1", {}).get("name") == "温度", f"d1.name='温度': {props.get('d1',{}).get('name')}")
    result(props.get("d1", {}).get("unit") == "℃",  f"d1.unit='℃': {props.get('d1',{}).get('unit')}")
    result(props.get("d3", {}).get("type") == "event", f"d3.type='event': {props.get('d3',{}).get('type')}")

    # ──────────────────────────────────
    # 7. 稼働時間・稼働率
    # ──────────────────────────────────
    header("7. 稼働時間・稼働率")

    start_str = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    end_str   = now.strftime("%Y-%m-%d %H:%M:%S")

    uptime = await db.query_uptime(TEST_CHANNEL_ID, field=3,
                                    start=start_str, end=end_str)
    result("on_seconds" in uptime and "total_seconds" in uptime and "rate" in uptime,
           f"query_uptime() キー確認: {list(uptime.keys())}")
    result(
        150 <= uptime["on_seconds"] <= 200,
        f"on_seconds≈180秒: {uptime['on_seconds']}秒"
    )
    result(
        uptime["total_seconds"] == 3600,
        f"total_seconds=3600: {uptime['total_seconds']}秒"
    )
    result(
        0 < uptime["rate"] < 10,
        f"rate={uptime['rate']}%（0〜10%の範囲内）"
    )

    # ──────────────────────────────────
    # 8. 現在状態クエリ
    # ──────────────────────────────────
    header("8. 現在の稼働状態（query_current_state）")

    states = await db.query_current_state(TEST_CHANNEL_ID)
    result(len(states) >= 1, f"query_current_state() → {len(states)} フィールド")
    if states:
        s = next((s for s in states if s["field"] == 3), None)
        result(s is not None, "field=3 の状態が存在")
        if s:
            result(s["state"] == 0, f"field=3 の最新状態=0(OFF): {s['state']}")

    # ──────────────────────────────────
    # クリーンアップ
    # ──────────────────────────────────
    header("クリーンアップ")
    pool = db._pool_ok()
    async with pool.acquire() as conn:
        await cleanup(conn)
    result(True, f"ch{TEST_CHANNEL_ID} のテストデータを全削除")

    await db.close_pool()

    # ──────────────────────────────────
    # 結果サマリ
    # ──────────────────────────────────
    print()
    print("=" * 60)
    if _fail_count == 0:
        print("  🎉 全テスト PASS！DB接続・読み書きは正常です")
    else:
        print(f"  ⚠️  {_fail_count} 件のテストが失敗しました")
    print("=" * 60)
    print()

    return _fail_count == 0


if __name__ == "__main__":
    ok = asyncio.run(run_tests())
    sys.exit(0 if ok else 1)
