"""
Senhub サーバー（メモリストレージ・DB実装予定）

起動方法（自動設定）:
    python main.py                     # config.py / .env の設定を使用

起動方法（uvicorn 直接・設定上書き）:
    # HTTP（開発・社内LAN）
    uvicorn main:app --host 0.0.0.0 --port 8000

    # HTTPS（本番）
    uvicorn main:app --host 0.0.0.0 --port 443 \
        --ssl-certfile /etc/letsencrypt/live/senhub.hide.link/fullchain.pem \
        --ssl-keyfile  /etc/letsencrypt/live/senhub.hide.link/privkey.pem

設定変更:
    server/.env        ネットワーク・TLS設定（.env.example を参考に）
    server/channels.yaml  チャンネルID・キー管理（channels.yaml.example を参考に）

注意: DB未設定時はプロセス終了でデータが消える（DB実装は後で追加予定）
"""
from fastapi import FastAPI, Request, Query
from fastapi.responses import PlainTextResponse
from datetime import datetime
from typing import Optional
import json
import config  # server/config.py

app = FastAPI(title="Senhub テストサーバー", version="0.1.0")

# ------------------------------------------------------------------
# メモリストレージ
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
    チャンネルを取得する。

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


def _ts_to_str(ts: str) -> str:
    """UNIX タイムスタンプ文字列 → 日時文字列"""
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return _now()


def _row_to_csv(row: dict) -> str:
    """1 行分の dict を CSV 文字列に変換"""
    parts = [row.get("created", "")]
    for i in range(1, 9):
        v = row.get(f"d{i}")
        parts.append(str(v) if v is not None else "")
    return ",".join(parts)


# ------------------------------------------------------------------
# データ受信 / 取得（GET /data）
# ------------------------------------------------------------------
@app.get("/api/v1/channels/{channel_id}/data", response_class=PlainTextResponse)
async def data_endpoint(
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
    ch = _get_channel(channel_id)
    if ch is None:
        return PlainTextResponse("Channel Not Found", status_code=404)

    # ---- 書き込みモード (writeKey あり) ----
    if writeKey is not None:
        if writeKey != ch["write_key"]:
            return PlainTextResponse("Unauthorized", status_code=401)

        row = {
            "created": _now(),
            "d1": d1, "d2": d2, "d3": d3, "d4": d4,
            "d5": d5, "d6": d6, "d7": d7, "d8": d8,
        }
        ch["data"].append(row)
        _trim(ch)
        return PlainTextResponse("200", status_code=200)

    # ---- 読み取りモード (readKey あり) ----
    if readKey is not None:
        if readKey != ch["read_key"]:
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

        # resolution は DB実装後に集約処理を追加予定
        # 現在は raw データをそのまま返す
        header = "created,d1,d2,d3,d4,d5,d6,d7,d8"
        lines  = [header] + [_row_to_csv(r) for r in data]
        return PlainTextResponse("\n".join(lines))

    return PlainTextResponse("Bad Request: writeKey or readKey required", status_code=400)


# ------------------------------------------------------------------
# バッチ受信（POST /dataarray）
# ------------------------------------------------------------------
@app.post("/api/v1/channels/{channel_id}/dataarray", response_class=PlainTextResponse)
async def receive_batch(channel_id: int, request: Request):
    ch   = _get_channel(channel_id)
    if ch is None:
        return PlainTextResponse("Channel Not Found", status_code=404)
    body = (await request.body()).decode("utf-8")
    lines = body.strip().split("\n")

    if not lines or not lines[0].startswith("writeKey="):
        return PlainTextResponse("Bad Request", status_code=400)

    write_key = lines[0].split("=", 1)[1].strip()
    if write_key != ch["write_key"]:
        return PlainTextResponse("Unauthorized", status_code=401)

    count = 0
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split(",")
        # フォーマット: ts,d1,d2,d3,d4,d5,d6,d7,d8
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
async def receive_event(channel_id: int, request: Request):
    ch   = _get_channel(channel_id)
    if ch is None:
        return PlainTextResponse("Channel Not Found", status_code=404)
    body = (await request.body()).decode("utf-8")
    lines = body.strip().split("\n")

    if not lines or not lines[0].startswith("writeKey="):
        return PlainTextResponse("Bad Request", status_code=400)

    write_key = lines[0].split("=", 1)[1].strip()
    if write_key != ch["write_key"]:
        return PlainTextResponse("Unauthorized", status_code=401)

    count = 0
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split(",")
        # フォーマット: ts,field_no,state
        if len(parts) < 3:
            continue

        created   = _ts_to_str(parts[0])
        field_no  = parts[1].strip()
        state_val = parts[2].strip()

        row = {"created": created}
        for i in range(1, 9):
            row[f"d{i}"] = None
        row[f"d{field_no}"] = state_val

        ch["data"].append(row)
        count += 1

    _trim(ch)
    return PlainTextResponse(f"200 count={count}", status_code=200)


# ------------------------------------------------------------------
# データエクスポート（GET /export）
# ------------------------------------------------------------------
@app.get("/api/v1/channels/{channel_id}/export", response_class=PlainTextResponse)
async def export_data(
    channel_id: int,
    readKey: str,
    format: str = "csv",
    start:  Optional[str] = None,
    end:    Optional[str] = None,
):
    ch = _get_channel(channel_id)
    if ch is None:
        return PlainTextResponse("Channel Not Found", status_code=404)
    if readKey != ch["read_key"]:
        return PlainTextResponse("Unauthorized", status_code=401)

    data = ch["data"]
    if start: data = [r for r in data if r["created"] >= start]
    if end:   data = [r for r in data if r["created"] <= end]

    if format == "json":
        return PlainTextResponse(
            json.dumps(data, ensure_ascii=False, indent=2),
            media_type="application/json",
        )

    # CSV（デフォルト）
    header = "created,d1,d2,d3,d4,d5,d6,d7,d8"
    lines  = [header] + [_row_to_csv(r) for r in data]
    return PlainTextResponse("\n".join(lines), media_type="text/csv")


# ------------------------------------------------------------------
# チャンネル設定取得（GET /properties）
# ------------------------------------------------------------------
@app.get("/api/v1/channels/{channel_id}/properties", response_class=PlainTextResponse)
async def get_properties(
    channel_id: int,
    readKey: Optional[str] = None,
):
    ch = _get_channel(channel_id)
    if ch is None:
        return PlainTextResponse("Channel Not Found", status_code=404)

    lines = [f"channelId={channel_id}"]
    for field, attrs in ch["properties"].items():
        for attr, val in attrs.items():
            lines.append(f"{field}.{attr}={val}")

    return PlainTextResponse("\n".join(lines))


# ------------------------------------------------------------------
# チャンネル設定更新（POST /properties）
# ------------------------------------------------------------------
@app.post("/api/v1/channels/{channel_id}/properties", response_class=PlainTextResponse)
async def set_properties(
    channel_id: int,
    request: Request,
    writeKey: Optional[str] = None,
):
    ch = _get_channel(channel_id)
    if ch is None:
        return PlainTextResponse("Channel Not Found", status_code=404)
    if writeKey != ch["write_key"]:
        return PlainTextResponse("Unauthorized", status_code=401)

    body = (await request.body()).decode("utf-8")
    for line in body.strip().split("\n"):
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()

        # 形式: d1.name=温度
        if "." in k:
            field, attr = k.split(".", 1)
            if field in ch["properties"] and attr in ("name", "unit", "type"):
                ch["properties"][field][attr] = v

    return PlainTextResponse("200", status_code=200)


# ------------------------------------------------------------------
# デバッグ用: 保存データ確認（GET /debug）
# ------------------------------------------------------------------
@app.get("/api/v1/channels/{channel_id}/debug")
async def debug(channel_id: int):
    ch = _get_channel(channel_id)
    return {
        "channel_id":   channel_id,
        "record_count": len(ch["data"]),
        "latest":       ch["data"][-3:] if ch["data"] else [],
        "properties":   ch["properties"],
    }


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
