"""
Senhub サーバー（メモリ / TimescaleDB 切り替え対応）

起動方法（自動設定）:
    python main.py                     # config.py / .env の設定を使用

起動方法（uvicorn 直接・設定上書き）:
    # HTTP（開発・社内LAN）
    uvicorn main:app --host 0.0.0.0 --port 8000

    # HTTPS（本番）
    uvicorn main:app --host 0.0.0.0 --port 443 \
        --ssl-certfile /etc/letsencrypt/live/senhub.example.com/fullchain.pem \
        --ssl-keyfile  /etc/letsencrypt/live/senhub.example.com/privkey.pem

設定変更:
    server/.env           ネットワーク・TLS・DB設定（.env.example を参考に）
    server/channels.yaml  チャンネルID・キー管理（channels.yaml.example を参考に）

DBモード:
    SENHUB_DB_URL=postgresql://senhub:senhubpass@localhost:5432/senhub を設定するとDBモードで起動。
    未設定の場合はメモリモード（プロセス終了でデータが消える）。
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Query
from fastapi.responses import PlainTextResponse
from datetime import datetime
from typing import Optional
import json
import hmac
import logging
import config  # server/config.py

# slowapi によるレート制限
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

logger = logging.getLogger("senhub")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# リクエストボディの最大サイズ（1MB）
MAX_BODY_BYTES = 1 * 1024 * 1024

# n パラメータの最大件数
MAX_ROWS = 10_000

# d1〜d8 センサー値の最大文字列長（floatとして解釈されるが念のため）
MAX_VALUE_LEN = 64

# 有効な resolution 値
VALID_RESOLUTIONS = {"raw", "1min", "1hour"}


def _keys_equal(a: Optional[str], b: str) -> bool:
    """タイミングアタック耐性のある文字列比較。a が None の場合は False を返す"""
    if a is None:
        return False
    return hmac.compare_digest(a.encode(), b.encode())


def _valid_date(s: Optional[str]) -> bool:
    """'YYYY-MM-DD' 形式の日付文字列かどうかを検証する"""
    if s is None:
        return True
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _valid_dt(s: Optional[str]) -> bool:
    """ISO 8601 形式の日時文字列かどうかを検証する"""
    if s is None:
        return True
    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        return False

if config.USE_DB:
    import db  # server/db.py


# ------------------------------------------------------------------
# lifespan: DB プール初期化 / クローズ
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.USE_DB:
        await db.init_pool()
    yield
    if config.USE_DB:
        await db.close_pool()


limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

app = FastAPI(
    title="Senhub サーバー",
    version="0.2.0",
    lifespan=lifespan,
    # SENHUB_DEBUG=true のときだけ Swagger UI / ReDoc を公開する
    # デフォルト（本番）では外部に API 構造を漏らさない
    docs_url    ="/docs"        if config.DEBUG else None,
    redoc_url   ="/redoc"       if config.DEBUG else None,
    openapi_url ="/openapi.json" if config.DEBUG else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ------------------------------------------------------------------
# メモリストレージ（USE_DB=False の場合のみ使用）
# チャンネル構造:
#   {
#       channel_id: {
#           "write_key":  str,
#           "read_key":   str,
#           "data":       [{"created": str, "d1": str|None, ... "d8": str|None}],
#           "properties": {"d1": {"name": str, "unit": str, "type": str}, ...},
#       }
#   }
# ------------------------------------------------------------------
_store: dict = {}

# 設定値（config.py / .env で変更可）
DEFAULT_WRITE_KEY = config.DEFAULT_WRITE_KEY
DEFAULT_READ_KEY  = config.DEFAULT_READ_KEY
MAX_RECORDS       = config.MAX_RECORDS


def _get_channel(channel_id: int):
    """
    チャンネルを取得する（メモリモード専用）。

    channels.yaml がある場合（セキュリティモード）:
        - 定義済みチャンネルは channels.yaml のキーで認証
        - 未定義チャンネルは None を返す（呼び出し元で 404 を返すこと）

    channels.yaml がない場合（開発モード）:
        - 全チャンネルをデフォルトキーで自動作成
    """
    if channel_id not in _store:
        ch_cfg = config.CHANNELS.get(channel_id)

        if ch_cfg:
            # channels.yaml に定義されたキーを使用
            write_key = ch_cfg["write_key"]
            read_key  = ch_cfg["read_key"]
        elif config.CHANNELS_FILE_LOADED:
            # channels.yaml はあるが、このチャンネルは未定義 → アクセス拒否
            return None
        else:
            # channels.yaml なし（開発モード）: デフォルトキーで自動作成
            write_key = DEFAULT_WRITE_KEY
            read_key  = DEFAULT_READ_KEY

        _store[channel_id] = {
            "write_key": write_key,
            "read_key":  read_key,
            "data":      [],
            "properties": {
                f"d{i}": {"name": f"d{i}", "unit": "", "type": "sensor"}
                for i in range(1, 9)
            },
        }
    return _store[channel_id]


def _trim(ch: dict):
    """メモリ上限を超えたら古いデータを削除"""
    if len(ch["data"]) > MAX_RECORDS:
        ch["data"] = ch["data"][-MAX_RECORDS:]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_TS_MIN = datetime(2020, 1, 1)  # これより古い場合はサーバー時刻で上書き


def _ts_to_str(ts: str) -> str:
    """UNIX タイムスタンプ文字列 → 日時文字列（NTP未同期は現在時刻にフォールバック）"""
    try:
        dt = datetime.fromtimestamp(int(ts))
        return dt.strftime("%Y-%m-%d %H:%M:%S") if dt >= _TS_MIN else _now()
    except Exception:
        return _now()


def _ts_to_dt(ts: str) -> datetime:
    """UNIX タイムスタンプ文字列 → datetime（NTP未同期は現在時刻にフォールバック）"""
    try:
        dt = datetime.fromtimestamp(int(ts))
        return dt if dt >= _TS_MIN else datetime.now()
    except Exception:
        return datetime.now()


# CSV インジェクション対策: スプレッドシートで数式として解釈される文字
_CSV_DANGER = ('=', '+', '@', '-', '\t', '\r')


def _row_to_csv(row: dict) -> str:
    """1 行分の dict を CSV 文字列に変換（CSV インジェクション対策済み）"""
    parts = [row.get("created", "")]
    for i in range(1, 9):
        v = row.get(f"d{i}")
        if v is not None:
            s = str(v)
            if s and s[0] in _CSV_DANGER:
                s = "'" + s  # 先頭にシングルクォートを付与して無害化
            parts.append(s)
        else:
            parts.append("")
    return ",".join(parts)


def _valid_channel_id(channel_id: int) -> bool:
    """channel_id の値域チェック（1〜65535）"""
    return 1 <= channel_id <= 65535


# ------------------------------------------------------------------
# データ受信 / 取得（GET /data）
# ------------------------------------------------------------------
@app.get("/api/v1/channels/{channel_id}/data", response_class=PlainTextResponse)
@limiter.limit("120/minute")
async def data_endpoint(
    request: Request,
    channel_id: int,
    writeKey: Optional[str] = None,
    readKey:  Optional[str] = None,
    n:          Optional[int] = None,
    date:       Optional[str] = None,
    start:      Optional[str] = None,
    end:        Optional[str] = None,
    resolution: Optional[str] = "raw",
    d1: Optional[str] = None,
    d2: Optional[str] = None,
    d3: Optional[str] = None,
    d4: Optional[str] = None,
    d5: Optional[str] = None,
    d6: Optional[str] = None,
    d7: Optional[str] = None,
    d8: Optional[str] = None,
):
    # channel_id の値域チェック
    if not _valid_channel_id(channel_id):
        return PlainTextResponse("Bad Request: invalid channel_id", status_code=400)

    # n の上限チェック
    if n is not None and n > MAX_ROWS:
        return PlainTextResponse(f"Bad Request: n must be <= {MAX_ROWS}", status_code=400)

    # resolution バリデーション
    if resolution not in VALID_RESOLUTIONS:
        return PlainTextResponse(
            f"Bad Request: resolution must be one of {', '.join(sorted(VALID_RESOLUTIONS))}",
            status_code=400,
        )

    # 日付パラメータのフォーマット検証
    if not _valid_date(date):
        return PlainTextResponse("Bad Request: invalid date format (expected YYYY-MM-DD)", status_code=400)
    if not _valid_dt(start):
        return PlainTextResponse("Bad Request: invalid start format (expected ISO 8601)", status_code=400)
    if not _valid_dt(end):
        return PlainTextResponse("Bad Request: invalid end format (expected ISO 8601)", status_code=400)

    # d1〜d8 の値の長さチェック
    for val in (d1, d2, d3, d4, d5, d6, d7, d8):
        if val is not None and len(val) > MAX_VALUE_LEN:
            return PlainTextResponse(f"Bad Request: sensor value too long (max {MAX_VALUE_LEN} chars)", status_code=400)

    # ---- DB モード ----
    if config.USE_DB:
        ch = await db.get_or_create_channel(channel_id)
        if ch is None:
            return PlainTextResponse("Channel Not Found", status_code=404)

        # 書き込みモード (writeKey あり)
        if writeKey is not None:
            if not _keys_equal(writeKey, ch["write_key"]):
                return PlainTextResponse("Unauthorized", status_code=401)
            await db.insert_sensor_row(
                channel_id, datetime.now(),
                d1=d1, d2=d2, d3=d3, d4=d4,
                d5=d5, d6=d6, d7=d7, d8=d8,
            )
            return PlainTextResponse("200", status_code=200)

        # 読み取りモード (readKey あり)
        if readKey is not None:
            if not _keys_equal(readKey, ch["read_key"]):
                return PlainTextResponse("Unauthorized", status_code=401)
            data = await db.query_sensor_data(channel_id, n=n, date=date,
                                              start=start, end=end,
                                              resolution=resolution or "raw")
            header = "created,d1,d2,d3,d4,d5,d6,d7,d8"
            lines  = [header] + [_row_to_csv(r) for r in data]
            return PlainTextResponse("\n".join(lines))

        return PlainTextResponse("Bad Request: writeKey or readKey required", status_code=400)

    # ---- メモリモード ----
    ch = _get_channel(channel_id)
    if ch is None:
        return PlainTextResponse("Channel Not Found", status_code=404)

    # 書き込みモード (writeKey あり)
    if writeKey is not None:
        if not _keys_equal(writeKey, ch["write_key"]):
            return PlainTextResponse("Unauthorized", status_code=401)

        row = {
            "created": _now(),
            "d1": d1, "d2": d2, "d3": d3, "d4": d4,
            "d5": d5, "d6": d6, "d7": d7, "d8": d8,
        }
        ch["data"].append(row)
        _trim(ch)
        return PlainTextResponse("200", status_code=200)

    # 読み取りモード (readKey あり)
    if readKey is not None:
        if not _keys_equal(readKey, ch["read_key"]):
            return PlainTextResponse("Unauthorized", status_code=401)

        data = ch["data"]

        # フィルタリング
        if date:
            data = [r for r in data if r["created"].startswith(date)]
        if start:
            data = [r for r in data if r["created"] >= start]
        if end:
            data = [r for r in data if r["created"] <= end]
        if n:
            data = data[-n:]

        header = "created,d1,d2,d3,d4,d5,d6,d7,d8"
        lines  = [header] + [_row_to_csv(r) for r in data]
        return PlainTextResponse("\n".join(lines))

    return PlainTextResponse("Bad Request: writeKey or readKey required", status_code=400)


# ------------------------------------------------------------------
# バッチ受信（POST /dataarray）
# ------------------------------------------------------------------
@app.post("/api/v1/channels/{channel_id}/dataarray", response_class=PlainTextResponse)
@limiter.limit("120/minute")
async def receive_batch(channel_id: int, request: Request):
    if not _valid_channel_id(channel_id):
        return PlainTextResponse("Bad Request: invalid channel_id", status_code=400)

    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return PlainTextResponse("Request Too Large", status_code=413)
    body = raw.decode("utf-8")
    lines = body.strip().split("\n")

    if not lines or not lines[0].startswith("writeKey="):
        return PlainTextResponse("Bad Request", status_code=400)

    write_key = lines[0].split("=", 1)[1].strip()

    # ---- DB モード ----
    if config.USE_DB:
        ch = await db.get_or_create_channel(channel_id)
        if ch is None:
            return PlainTextResponse("Channel Not Found", status_code=404)
        if not _keys_equal(write_key, ch["write_key"]):
            return PlainTextResponse("Unauthorized", status_code=401)

        rows = []
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            try:
                ts = _ts_to_dt(parts[0]) if len(parts) > 0 else datetime.now()
            except Exception as e:
                logger.warning("[ch%d] invalid timestamp %r: %s", channel_id, parts[0] if parts else "", e)
                continue
            row = {"ts": ts}
            for i in range(1, 9):
                val = parts[i].strip() if i < len(parts) else ""
                row[f"d{i}"] = val if val != "" else None
            rows.append(row)

        count = await db.insert_sensor_rows(channel_id, rows)
        return PlainTextResponse(f"200 count={count}", status_code=200)

    # ---- メモリモード ----
    ch = _get_channel(channel_id)
    if ch is None:
        return PlainTextResponse("Channel Not Found", status_code=404)
    if not _keys_equal(write_key, ch["write_key"]):
        return PlainTextResponse("Unauthorized", status_code=401)

    count = 0
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split(",")
        created = _ts_to_str(parts[0]) if len(parts) > 0 else _now()

        row = {"created": created}
        for i in range(1, 9):
            val = parts[i].strip() if i < len(parts) else ""
            row[f"d{i}"] = val if val != "" else None

        ch["data"].append(row)
        count += 1

    _trim(ch)
    return PlainTextResponse(f"200 count={count}", status_code=200)


# ------------------------------------------------------------------
# ON/OFF イベント受信（POST /event）
# ------------------------------------------------------------------
@app.post("/api/v1/channels/{channel_id}/event", response_class=PlainTextResponse)
@limiter.limit("120/minute")
async def receive_event(channel_id: int, request: Request):
    if not _valid_channel_id(channel_id):
        return PlainTextResponse("Bad Request: invalid channel_id", status_code=400)

    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return PlainTextResponse("Request Too Large", status_code=413)
    body = raw.decode("utf-8")
    lines = body.strip().split("\n")

    if not lines or not lines[0].startswith("writeKey="):
        return PlainTextResponse("Bad Request", status_code=400)

    write_key = lines[0].split("=", 1)[1].strip()

    # ---- DB モード ----
    if config.USE_DB:
        ch = await db.get_or_create_channel(channel_id)
        if ch is None:
            return PlainTextResponse("Channel Not Found", status_code=404)
        if not _keys_equal(write_key, ch["write_key"]):
            return PlainTextResponse("Unauthorized", status_code=401)

        count = 0
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue
            ts = _ts_to_dt(parts[0])
            # field_no: 1〜8 の範囲チェック
            try:
                field_no = int(parts[1].strip())
                if not 1 <= field_no <= 8:
                    continue
            except ValueError:
                continue
            # state_v: 0 または 1 のみ許可
            try:
                state_v = int(parts[2].strip())
                if state_v not in (0, 1):
                    continue
            except ValueError:
                continue
            await db.insert_event(channel_id, ts, field_no, state_v)
            count += 1

        return PlainTextResponse(f"200 count={count}", status_code=200)

    # ---- メモリモード ----
    ch = _get_channel(channel_id)
    if ch is None:
        return PlainTextResponse("Channel Not Found", status_code=404)
    if not _keys_equal(write_key, ch["write_key"]):
        return PlainTextResponse("Unauthorized", status_code=401)

    count = 0
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split(",")
        if len(parts) < 3:
            continue

        created = _ts_to_str(parts[0])
        # field_no: 1〜8 の範囲チェック（DBモードと同等）
        try:
            field_no = int(parts[1].strip())
            if not 1 <= field_no <= 8:
                continue
        except ValueError:
            continue
        # state_val: 0 または 1 のみ許可
        try:
            state_val = int(parts[2].strip())
            if state_val not in (0, 1):
                continue
        except ValueError:
            continue

        row = {"created": created}
        for i in range(1, 9):
            row[f"d{i}"] = None
        row[f"d{field_no}"] = str(state_val)

        ch["data"].append(row)
        count += 1

    _trim(ch)
    return PlainTextResponse(f"200 count={count}", status_code=200)


# ------------------------------------------------------------------
# データエクスポート（GET /export）
# ------------------------------------------------------------------
@app.get("/api/v1/channels/{channel_id}/export", response_class=PlainTextResponse)
@limiter.limit("10/minute")
async def export_data(
    request: Request,
    channel_id: int,
    readKey: str,
    format: str = "csv",
    start:  Optional[str] = None,
    end:    Optional[str] = None,
):
    if not _valid_channel_id(channel_id):
        return PlainTextResponse("Bad Request: invalid channel_id", status_code=400)

    # 日付パラメータのフォーマット検証
    if not _valid_dt(start):
        return PlainTextResponse("Bad Request: invalid start format (expected ISO 8601)", status_code=400)
    if not _valid_dt(end):
        return PlainTextResponse("Bad Request: invalid end format (expected ISO 8601)", status_code=400)

    # ---- DB モード ----
    if config.USE_DB:
        ch = await db.get_or_create_channel(channel_id)
        if ch is None:
            return PlainTextResponse("Channel Not Found", status_code=404)
        if not _keys_equal(readKey, ch["read_key"]):
            return PlainTextResponse("Unauthorized", status_code=401)

        data = await db.query_sensor_data(channel_id, start=start, end=end)

        if format == "json":
            return PlainTextResponse(
                json.dumps(data, ensure_ascii=False, indent=2),
                media_type="application/json",
            )
        header = "created,d1,d2,d3,d4,d5,d6,d7,d8"
        lines  = [header] + [_row_to_csv(r) for r in data]
        return PlainTextResponse("\n".join(lines), media_type="text/csv")

    # ---- メモリモード ----
    ch = _get_channel(channel_id)
    if ch is None:
        return PlainTextResponse("Channel Not Found", status_code=404)
    if not _keys_equal(readKey, ch["read_key"]):
        return PlainTextResponse("Unauthorized", status_code=401)

    data = ch["data"]
    if start: data = [r for r in data if r["created"] >= start]
    if end:   data = [r for r in data if r["created"] <= end]

    if format == "json":
        return PlainTextResponse(
            json.dumps(data, ensure_ascii=False, indent=2),
            media_type="application/json",
        )

    header = "created,d1,d2,d3,d4,d5,d6,d7,d8"
    lines  = [header] + [_row_to_csv(r) for r in data]
    return PlainTextResponse("\n".join(lines), media_type="text/csv")


# ------------------------------------------------------------------
# チャンネル設定取得（GET /properties）
# ------------------------------------------------------------------
@app.get("/api/v1/channels/{channel_id}/properties", response_class=PlainTextResponse)
@limiter.limit("30/minute")
async def get_properties(
    request: Request,
    channel_id: int,
    readKey: Optional[str] = None,
):
    if not _valid_channel_id(channel_id):
        return PlainTextResponse("Bad Request: invalid channel_id", status_code=400)
    # ---- DB モード ----
    if config.USE_DB:
        ch = await db.get_or_create_channel(channel_id)
        if ch is None:
            return PlainTextResponse("Channel Not Found", status_code=404)
        if not _keys_equal(readKey, ch["read_key"]):
            return PlainTextResponse("Unauthorized", status_code=401)

        props = await db.get_properties(channel_id)
        lines = [f"channelId={channel_id}"]
        for field, attrs in props.items():
            for attr, val in attrs.items():
                lines.append(f"{field}.{attr}={val}")
        return PlainTextResponse("\n".join(lines))

    # ---- メモリモード ----
    ch = _get_channel(channel_id)
    if ch is None:
        return PlainTextResponse("Channel Not Found", status_code=404)
    if not _keys_equal(readKey, ch["read_key"]):
        return PlainTextResponse("Unauthorized", status_code=401)

    lines = [f"channelId={channel_id}"]
    for field, attrs in ch["properties"].items():
        for attr, val in attrs.items():
            lines.append(f"{field}.{attr}={val}")

    return PlainTextResponse("\n".join(lines))


# ------------------------------------------------------------------
# チャンネル設定更新（POST /properties）
# ------------------------------------------------------------------
@app.post("/api/v1/channels/{channel_id}/properties", response_class=PlainTextResponse)
@limiter.limit("30/minute")
async def set_properties(
    channel_id: int,
    request: Request,
    writeKey: Optional[str] = None,
):
    if not _valid_channel_id(channel_id):
        return PlainTextResponse("Bad Request: invalid channel_id", status_code=400)

    body = (await request.body()).decode("utf-8")

    # ---- DB モード ----
    if config.USE_DB:
        ch = await db.get_or_create_channel(channel_id)
        if ch is None:
            return PlainTextResponse("Channel Not Found", status_code=404)
        if writeKey is None or not _keys_equal(writeKey, ch["write_key"]):
            return PlainTextResponse("Unauthorized", status_code=401)

        updates: dict = {}
        for line in body.strip().split("\n"):
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if "." in k:
                field, attr = k.split(".", 1)
                if field.startswith("d") and attr in ("name", "unit", "type"):
                    if field not in updates:
                        updates[field] = {}
                    updates[field][attr] = v

        if updates:
            await db.set_properties(channel_id, updates)
        return PlainTextResponse("200", status_code=200)

    # ---- メモリモード ----
    ch = _get_channel(channel_id)
    if ch is None:
        return PlainTextResponse("Channel Not Found", status_code=404)
    if writeKey is None or not _keys_equal(writeKey, ch["write_key"]):
        return PlainTextResponse("Unauthorized", status_code=401)

    for line in body.strip().split("\n"):
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()

        if "." in k:
            field, attr = k.split(".", 1)
            if field in ch["properties"] and attr in ("name", "unit", "type"):
                ch["properties"][field][attr] = v

    return PlainTextResponse("200", status_code=200)


# ------------------------------------------------------------------
# デバッグ用: 保存データ確認（GET /debug）
# ------------------------------------------------------------------
@app.get("/api/v1/channels/{channel_id}/debug")
@limiter.limit("30/minute")
async def debug(request: Request, channel_id: int, readKey: Optional[str] = None):
    if not _valid_channel_id(channel_id):
        return PlainTextResponse("Bad Request: invalid channel_id", status_code=400)
    if config.USE_DB:
        ch = await db.get_or_create_channel(channel_id)
        if ch is None:
            return PlainTextResponse("Channel Not Found", status_code=404)
        if readKey is None or not _keys_equal(readKey, ch["read_key"]):
            return PlainTextResponse("Unauthorized", status_code=401)
        data = await db.query_sensor_data(channel_id, n=3)
        props = await db.get_properties(channel_id)
        return {
            "channel_id":   channel_id,
            "mode":         "db",
            "record_count": "N/A (use DB directly)",
            "latest":       data[-3:] if data else [],
            "properties":   props,
        }

    ch = _get_channel(channel_id)
    if ch is None:
        return PlainTextResponse("Channel Not Found", status_code=404)
    if readKey is None or not _keys_equal(readKey, ch["read_key"]):
        return PlainTextResponse("Unauthorized", status_code=401)
    return {
        "channel_id":   channel_id,
        "mode":         "memory",
        "record_count": len(ch["data"]),
        "latest":       ch["data"][-3:] if ch["data"] else [],
        "properties":   ch["properties"],
    }


# ------------------------------------------------------------------
# Web画面向け: 現在の稼働状態（GET /state）
# ------------------------------------------------------------------
@app.get("/api/v1/channels/{channel_id}/state", response_class=PlainTextResponse)
@limiter.limit("60/minute")
async def get_state(
    request: Request,
    channel_id: int,
    readKey: Optional[str] = None,
):
    if not _valid_channel_id(channel_id):
        return PlainTextResponse("Bad Request: invalid channel_id", status_code=400)
    if config.USE_DB:
        ch = await db.get_or_create_channel(channel_id)
        if ch is None:
            return PlainTextResponse("Channel Not Found", status_code=404)
        if readKey is None or not _keys_equal(readKey, ch["read_key"]):
            return PlainTextResponse("Unauthorized", status_code=401)

        states = await db.query_current_state(channel_id)
        lines = [f"d{s['field']},{s['time']},{s['state']}" for s in states]
        return PlainTextResponse("\n".join(lines))

    # メモリモード: events テーブル相当の情報は _store にないので空返す
    return PlainTextResponse("", status_code=200)


# ------------------------------------------------------------------
# Web画面向け: イベント履歴（GET /events）
# ------------------------------------------------------------------
@app.get("/api/v1/channels/{channel_id}/events", response_class=PlainTextResponse)
@limiter.limit("60/minute")
async def get_events(
    request: Request,
    channel_id: int,
    readKey: Optional[str] = None,
    n: Optional[int] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    if not _valid_channel_id(channel_id):
        return PlainTextResponse("Bad Request: invalid channel_id", status_code=400)

    if n is not None and n > MAX_ROWS:
        return PlainTextResponse(f"Bad Request: n must be <= {MAX_ROWS}", status_code=400)
    if not _valid_dt(start):
        return PlainTextResponse("Bad Request: invalid start format (expected ISO 8601)", status_code=400)
    if not _valid_dt(end):
        return PlainTextResponse("Bad Request: invalid end format (expected ISO 8601)", status_code=400)

    if config.USE_DB:
        ch = await db.get_or_create_channel(channel_id)
        if ch is None:
            return PlainTextResponse("Channel Not Found", status_code=404)
        if readKey is None or not _keys_equal(readKey, ch["read_key"]):
            return PlainTextResponse("Unauthorized", status_code=401)

        events = await db.query_events(channel_id, n=n, start=start, end=end)
        lines = [
            f"{e['time']},{e['field']},{e['state']},{e['duration'] if e['duration'] is not None else ''}"
            for e in events
        ]
        return PlainTextResponse("\n".join(lines))

    return PlainTextResponse("", status_code=200)


# ------------------------------------------------------------------
# Web画面向け: 稼働時間・稼働率（GET /uptime）
# ------------------------------------------------------------------
@app.get("/api/v1/channels/{channel_id}/uptime", response_class=PlainTextResponse)
@limiter.limit("60/minute")
async def get_uptime(
    request: Request,
    channel_id: int,
    readKey: Optional[str] = None,
    field: int = 1,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    if not _valid_channel_id(channel_id):
        return PlainTextResponse("Bad Request: invalid channel_id", status_code=400)

    if not 1 <= field <= 8:
        return PlainTextResponse("Bad Request: field must be 1-8", status_code=400)
    if not _valid_dt(start):
        return PlainTextResponse("Bad Request: invalid start format (expected ISO 8601)", status_code=400)
    if not _valid_dt(end):
        return PlainTextResponse("Bad Request: invalid end format (expected ISO 8601)", status_code=400)

    if config.USE_DB:
        ch = await db.get_or_create_channel(channel_id)
        if ch is None:
            return PlainTextResponse("Channel Not Found", status_code=404)
        if readKey is None or not _keys_equal(readKey, ch["read_key"]):
            return PlainTextResponse("Unauthorized", status_code=401)

        result = await db.query_uptime(channel_id, field=field, start=start, end=end)
        line = f"{result['on_seconds']},{result['total_seconds']},{result['rate']}"
        return PlainTextResponse(line)

    return PlainTextResponse("0,0,0.0", status_code=200)


# ------------------------------------------------------------------
# エントリポイント: python main.py で直接起動可能
# ------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    config.show()  # 起動時に設定を表示

    uvicorn_kwargs = dict(
        app="main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
    )

    if config.USE_TLS:
        uvicorn_kwargs["ssl_certfile"] = config.TLS_CERT
        uvicorn_kwargs["ssl_keyfile"]  = config.TLS_KEY

    uvicorn.run(**uvicorn_kwargs)
