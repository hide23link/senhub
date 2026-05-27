"""
Senhub DB レイヤー（asyncpg + TimescaleDB）

このモジュールは config.USE_DB が True の場合のみ使用される。
FastAPI の lifespan で init_pool() / close_pool() を呼ぶこと。
"""
import asyncpg
from datetime import datetime, timezone, date as date_type
from zoneinfo import ZoneInfo
from typing import Optional

import config

_JST = ZoneInfo("Asia/Tokyo")

_pool: Optional[asyncpg.Pool] = None

FIELDS = ["d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8"]


# ──────────────────────────────────────────────────────────────
# ライフサイクル
# ──────────────────────────────────────────────────────────────

async def init_pool() -> None:
    """コネクションプールを初期化する（lifespan start で呼ぶ）"""
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=config.DB_URL,
        min_size=config.DB_POOL_MIN,
        max_size=config.DB_POOL_MAX,
        server_settings={"timezone": "Asia/Tokyo"},  # セッション TZ を JST に固定
    )
    print(f"[DB] 接続プール初期化完了 ({config.DB_POOL_MIN}〜{config.DB_POOL_MAX} connections)")


async def close_pool() -> None:
    """コネクションプールを閉じる（lifespan end で呼ぶ）"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        print("[DB] 接続プールをクローズしました")


def _pool_ok() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB プールが初期化されていません。init_pool() を呼んでください")
    return _pool


# ──────────────────────────────────────────────────────────────
# 内部ユーティリティ
# ──────────────────────────────────────────────────────────────

def _to_local_str(dt: datetime) -> str:
    """TIMESTAMPTZ (UTC) → JST 文字列 "YYYY-MM-DD HH:MM:SS" に変換"""
    return dt.astimezone(_JST).strftime("%Y-%m-%d %H:%M:%S")


def _parse_float(val) -> Optional[float]:
    """文字列・None・float → float | None"""
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _make_aware(dt: datetime) -> datetime:
    """naive datetime を JST aware に変換する（naive は JST として扱う）"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_JST)  # naive → JST aware
    return dt


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    """
    タイムスタンプ文字列 → aware datetime。
    asyncpg の TIMESTAMPTZ パラメータに渡す際に使用する。
    """
    if s is None:
        return None
    dt = datetime.fromisoformat(s)
    return _make_aware(dt)


# ──────────────────────────────────────────────────────────────
# チャンネル管理
# ──────────────────────────────────────────────────────────────

async def get_or_create_channel(channel_id: int) -> dict:
    """
    チャンネルを取得する。存在しなければ channels.yaml のキーで自動作成する。
    channels.yaml が未設定の場合はデフォルトキーで作成する。

    Returns: {"channel_id": int, "write_key": str, "read_key": str, "name": str}
    """
    pool = _pool_ok()

    ch_cfg = config.CHANNELS.get(channel_id)
    if ch_cfg:
        write_key = ch_cfg["write_key"]
        read_key  = ch_cfg["read_key"]
        name      = ch_cfg.get("name", "")
    elif config.CHANNELS_FILE_LOADED:
        # channels.yaml がある & 未定義チャンネル → アクセス拒否
        return None
    else:
        write_key = config.DEFAULT_WRITE_KEY
        read_key  = config.DEFAULT_READ_KEY
        name      = ""

    async with pool.acquire() as conn:
        # 既存チャンネルを取得。なければ INSERT（ON CONFLICT は何もしない）
        row = await conn.fetchrow(
            "SELECT channel_id, write_key, read_key, name FROM channels WHERE channel_id = $1",
            channel_id
        )
        if row is None:
            await conn.execute(
                """
                INSERT INTO channels (channel_id, write_key, read_key, name)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (channel_id) DO NOTHING
                """,
                channel_id, write_key, read_key, name
            )
            # d1〜d8 のデフォルトプロパティを一括INSERT
            await conn.executemany(
                """
                INSERT INTO channel_properties (channel_id, field, name, unit, type)
                VALUES ($1, $2, $3, '', 'sensor')
                ON CONFLICT DO NOTHING
                """,
                [(channel_id, f"d{i}", f"d{i}") for i in range(1, 9)]
            )
            row = await conn.fetchrow(
                "SELECT channel_id, write_key, read_key, name FROM channels WHERE channel_id = $1",
                channel_id
            )

    return dict(row)


async def get_channel(channel_id: int) -> Optional[dict]:
    """チャンネルを取得する。存在しなければ None を返す"""
    pool = _pool_ok()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT channel_id, write_key, read_key, name FROM channels WHERE channel_id = $1",
            channel_id
        )
    return dict(row) if row else None


# ──────────────────────────────────────────────────────────────
# センサーデータ
# ──────────────────────────────────────────────────────────────

async def insert_sensor_row(
    channel_id: int,
    ts: datetime,
    d1=None, d2=None, d3=None, d4=None,
    d5=None, d6=None, d7=None, d8=None,
) -> None:
    """センサーデータを1行INSERT（GET /data?writeKey= の単発送信用）"""
    pool = _pool_ok()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sensor_data (time, channel_id, d1,d2,d3,d4,d5,d6,d7,d8)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            """,
            ts, channel_id,
            _parse_float(d1), _parse_float(d2), _parse_float(d3), _parse_float(d4),
            _parse_float(d5), _parse_float(d6), _parse_float(d7), _parse_float(d8),
        )


async def insert_sensor_rows(channel_id: int, rows: list) -> int:
    """
    センサーデータをバッチINSERT（POST /dataarray 用）

    rows: [{"ts": datetime, "d1": str|float|None, ..., "d8": str|float|None}]
    Returns: 挿入成功件数
    """
    if not rows:
        return 0
    pool = _pool_ok()
    data = [
        (
            r["ts"], channel_id,
            _parse_float(r.get("d1")), _parse_float(r.get("d2")),
            _parse_float(r.get("d3")), _parse_float(r.get("d4")),
            _parse_float(r.get("d5")), _parse_float(r.get("d6")),
            _parse_float(r.get("d7")), _parse_float(r.get("d8")),
        )
        for r in rows
    ]
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO sensor_data (time, channel_id, d1,d2,d3,d4,d5,d6,d7,d8)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            """,
            data
        )
    return len(data)


async def query_sensor_data(
    channel_id: int,
    n: Optional[int] = None,
    date: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    resolution: str = "raw",
) -> list:
    """
    センサーデータを取得する。

    resolution:
        "raw"   → sensor_data テーブル
        "1min"  → sensor_data_1min ビュー
        "1hour" → sensor_data_1hour ビュー

    Returns: [{"created": "YYYY-MM-DD HH:MM:SS", "d1": float|None, ...}, ...]
    """
    pool = _pool_ok()

    if resolution == "1min":
        table, time_col = "sensor_data_1min",  "bucket"
    elif resolution == "1hour":
        table, time_col = "sensor_data_1hour", "bucket"
    else:
        table, time_col = "sensor_data",       "time"

    conditions = ["channel_id = $1"]
    params: list = [channel_id]
    idx = 2

    if date:
        # TIMESTAMPTZ::date はセッションタイムゾーンでの日付に変換される
        # asyncpg は date 型のパラメータに datetime.date オブジェクトを要求する
        conditions.append(f"{time_col}::date = ${idx}")
        params.append(datetime.strptime(date, "%Y-%m-%d").date()); idx += 1
    if start:
        conditions.append(f"{time_col} >= ${idx}")
        params.append(_parse_dt(start)); idx += 1
    if end:
        conditions.append(f"{time_col} <= ${idx}")
        params.append(_parse_dt(end)); idx += 1

    where = " AND ".join(conditions)

    if n:
        # 最新N件: DESC で取得してから ASC に並び替え
        params.append(n)
        sql = f"""
            SELECT * FROM (
                SELECT {time_col} AS t, channel_id,
                       d1,d2,d3,d4,d5,d6,d7,d8
                FROM {table}
                WHERE {where}
                ORDER BY {time_col} DESC
                LIMIT ${idx}
            ) sub ORDER BY t ASC
        """
    else:
        sql = f"""
            SELECT {time_col} AS t, channel_id,
                   d1,d2,d3,d4,d5,d6,d7,d8
            FROM {table}
            WHERE {where}
            ORDER BY {time_col} ASC
        """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    result = []
    for row in rows:
        r = {"created": _to_local_str(row["t"])}
        for f in FIELDS:
            r[f] = row[f]  # float | None
        result.append(r)
    return result


# ──────────────────────────────────────────────────────────────
# イベントデータ
# ──────────────────────────────────────────────────────────────

async def insert_event(
    channel_id: int,
    ts: datetime,
    field: int,
    state: int,
) -> None:
    """
    ON/OFFイベントを INSERT する。

    state=0 (OFF) の場合、直前の ON イベントを検索して
    duration（ON継続秒数）を計算してから INSERT する。
    state=1 (ON) の場合、duration=NULL で INSERT する。
    """
    pool = _pool_ok()
    duration = None

    # asyncpg は TIMESTAMPTZ を UTC aware で返すため、ts も aware に揃える
    ts_aware = _make_aware(ts)

    if state == 0:
        # 直前の ON イベントの時刻を取得して duration を計算
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT time FROM events
                WHERE channel_id = $1 AND field = $2 AND state = 1
                ORDER BY time DESC
                LIMIT 1
                """,
                channel_id, field
            )
        if row:
            # row["time"] は asyncpg が返す UTC aware datetime
            on_time = row["time"]
            if on_time.tzinfo is None:
                on_time = on_time.replace(tzinfo=timezone.utc)
            delta = ts_aware - on_time
            duration = max(0, int(delta.total_seconds()))

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO events (time, channel_id, field, state, duration)
            VALUES ($1, $2, $3, $4, $5)
            """,
            ts_aware, channel_id, field, state, duration
        )


# ──────────────────────────────────────────────────────────────
# プロパティ
# ──────────────────────────────────────────────────────────────

async def get_properties(channel_id: int) -> dict:
    """
    チャンネルのフィールドプロパティを取得する。

    Returns: {"d1": {"name": str, "unit": str, "type": str}, ...}
    """
    pool = _pool_ok()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT field, name, unit, type FROM channel_properties WHERE channel_id = $1",
            channel_id
        )
    return {row["field"]: {"name": row["name"], "unit": row["unit"], "type": row["type"]}
            for row in rows}


async def set_properties(channel_id: int, updates: dict) -> None:
    """
    フィールドプロパティを更新する。

    updates: {"d1": {"name": str, "unit": str, "type": str}, ...}
    """
    pool = _pool_ok()
    async with pool.acquire() as conn:
        for field, attrs in updates.items():
            await conn.execute(
                """
                INSERT INTO channel_properties (channel_id, field, name, unit, type)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (channel_id, field) DO UPDATE
                    SET name = EXCLUDED.name,
                        unit = EXCLUDED.unit,
                        type = EXCLUDED.type
                """,
                channel_id, field,
                attrs.get("name", ""),
                attrs.get("unit", ""),
                attrs.get("type", "sensor"),
            )


# ──────────────────────────────────────────────────────────────
# Web画面向けクエリ
# ──────────────────────────────────────────────────────────────

async def query_current_state(channel_id: int) -> list:
    """
    各フィールドの最新ON/OFF状態を取得する（GET /state 用）。

    Returns: [{"field": int, "time": str, "state": int}, ...]
    """
    pool = _pool_ok()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (field) field, time, state
            FROM events
            WHERE channel_id = $1
            ORDER BY field, time DESC
            """,
            channel_id
        )
    return [
        {"field": row["field"], "time": _to_local_str(row["time"]), "state": row["state"]}
        for row in rows
    ]


async def query_events(
    channel_id: int,
    n: Optional[int] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> list:
    """
    イベント履歴を取得する（GET /events 用）。

    Returns: [{"time": str, "field": int, "state": int, "duration": int|None}, ...]
    """
    pool = _pool_ok()
    conditions = ["channel_id = $1"]
    params: list = [channel_id]
    idx = 2

    if start:
        conditions.append(f"time >= ${idx}"); params.append(_parse_dt(start)); idx += 1
    if end:
        conditions.append(f"time <= ${idx}"); params.append(_parse_dt(end)); idx += 1

    where = " AND ".join(conditions)

    if n:
        params.append(n)
        sql = f"""
            SELECT * FROM (
                SELECT time, field, state, duration
                FROM events WHERE {where}
                ORDER BY time DESC LIMIT ${idx}
            ) sub ORDER BY time ASC
        """
    else:
        sql = f"""
            SELECT time, field, state, duration
            FROM events WHERE {where} ORDER BY time ASC
        """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    return [
        {
            "time": _to_local_str(row["time"]),
            "field": row["field"],
            "state": row["state"],
            "duration": row["duration"],
        }
        for row in rows
    ]


async def query_uptime(
    channel_id: int,
    field: int,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict:
    """
    稼働時間・稼働率を計算する（GET /uptime 用）。

    Returns:
        {"on_seconds": int, "total_seconds": int, "rate": float}
    """
    pool = _pool_ok()

    # 期間の始端・終端（ユーザー入力の naive datetime は JST として解釈）
    now_utc = datetime.now(timezone.utc)
    start_dt = _parse_dt(start).astimezone(timezone.utc) if start else None
    end_dt   = _parse_dt(end).astimezone(timezone.utc)   if end   else now_utc

    total_seconds = int((end_dt - (start_dt or end_dt)).total_seconds()) if start_dt else 0

    conditions = ["channel_id = $1", "field = $2", "state = 0"]
    params: list = [channel_id, field]
    idx = 3

    if start_dt:
        conditions.append(f"time >= ${idx}"); params.append(start_dt); idx += 1
    if end_dt != now_utc:
        conditions.append(f"time <= ${idx}"); params.append(end_dt); idx += 1

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        # OFF イベントに記録された duration の合計（= ON状態の継続時間合計）
        row = await conn.fetchrow(
            f"SELECT COALESCE(SUM(duration), 0) AS on_sec FROM events WHERE {where}",
            *params
        )
        on_seconds = int(row["on_sec"]) if row else 0

        # 現在も ON 中の場合、最後の ON イベント〜end_dt を加算
        last_on = await conn.fetchrow(
            """
            SELECT time FROM events
            WHERE channel_id = $1 AND field = $2
            ORDER BY time DESC LIMIT 1
            """,
            channel_id, field
        )
        if last_on:
            last_state = await conn.fetchrow(
                """
                SELECT state FROM events
                WHERE channel_id=$1 AND field=$2
                ORDER BY time DESC LIMIT 1
                """,
                channel_id, field
            )
            if last_state and last_state["state"] == 1:
                # 現在ON中: end_dt - 最終ONイベント時刻 を加算
                on_start = last_on["time"].replace(tzinfo=timezone.utc)
                on_seconds += max(0, int((end_dt - on_start).total_seconds()))

    rate = round(on_seconds / total_seconds * 100, 2) if total_seconds > 0 else 0.0
    return {"on_seconds": on_seconds, "total_seconds": total_seconds, "rate": rate}
