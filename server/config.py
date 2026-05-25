"""
Senhub サーバー設定

環境変数または .env ファイルで上書き可能。
.env ファイルは server/.env に配置する（.env.example を参考に）。

優先順位: 環境変数 > .env ファイル > デフォルト値
"""
import os
from pathlib import Path

# .env ファイルを読み込む（python-dotenv がある場合のみ）
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        # python-dotenv がなければ手動パース
        for line in _env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# ------------------------------------------------------------------
# ネットワーク設定
# ------------------------------------------------------------------

# サーバーがバインドするホスト（0.0.0.0 = 全NIF）
HOST: str = os.environ.get("SENHUB_HOST", "0.0.0.0")

# サーバーがリッスンするポート
# TLS有効時デフォルト: 443、無効時: 8000
_default_port = "443" if os.environ.get("SENHUB_USE_TLS", "true").lower() in ("true", "1", "yes") else "8000"
PORT: int = int(os.environ.get("SENHUB_PORT", _default_port))

# 公開ドメイン名（TLS証明書パスのデフォルト生成に使用）
DOMAIN: str = os.environ.get("SENHUB_DOMAIN", "senhub.hide.link")


# ------------------------------------------------------------------
# TLS 設定
# ------------------------------------------------------------------

# TLSを使用するか（false にすると HTTP で起動 ＝ 社内LAN・開発環境向け）
USE_TLS: bool = os.environ.get("SENHUB_USE_TLS", "true").lower() in ("true", "1", "yes")

# TLS証明書・秘密鍵のパス（USE_TLS=true の場合のみ使用）
TLS_CERT: str = os.environ.get(
    "SENHUB_TLS_CERT",
    f"/etc/letsencrypt/live/{DOMAIN}/fullchain.pem",
)
TLS_KEY: str = os.environ.get(
    "SENHUB_TLS_KEY",
    f"/etc/letsencrypt/live/{DOMAIN}/privkey.pem",
)


# ------------------------------------------------------------------
# API設定
# ------------------------------------------------------------------

# メモリ上の最大保持件数（DB実装後は不要）
MAX_RECORDS: int = int(os.environ.get("SENHUB_MAX_RECORDS", "10000"))

# テスト用デフォルトキー（channels.yaml が存在しない場合のフォールバック）
DEFAULT_WRITE_KEY: str = os.environ.get("SENHUB_DEFAULT_WRITE_KEY", "test_writeKey")
DEFAULT_READ_KEY: str  = os.environ.get("SENHUB_DEFAULT_READ_KEY",  "test_readKey")


# ------------------------------------------------------------------
# チャンネル管理（channels.yaml）
# ------------------------------------------------------------------

_channels_file = Path(__file__).parent / "channels.yaml"


def _load_channels() -> dict:
    """
    channels.yaml を読み込み {channel_id(int): {"name":…, "write_key":…, "read_key":…}} を返す。
    ファイルが存在しない、または読み込み失敗の場合は空 dict を返す。
    """
    if not _channels_file.exists():
        return {}
    try:
        import yaml  # pyyaml
        data = yaml.safe_load(_channels_file.read_text(encoding="utf-8"))
        raw  = (data or {}).get("channels") or {}
        return {int(k): v for k, v in raw.items()}
    except Exception as e:
        print(f"[WARNING] channels.yaml 読み込み失敗: {e}")
        return {}


# {channel_id: {"name": str, "write_key": str, "read_key": str}}
CHANNELS: dict = _load_channels()

# channels.yaml が存在してチャンネルが1件以上定義されていれば True
# → True の場合、未定義チャンネルへのアクセスを拒否する（セキュリティモード）
CHANNELS_FILE_LOADED: bool = bool(CHANNELS)


# ------------------------------------------------------------------
# DB設定（TimescaleDB / PostgreSQL）
# ------------------------------------------------------------------

# 接続URL例: postgresql://senhub:senhubpass@localhost:5432/senhub
# 未設定の場合はメモリモードで動作する
DB_URL:      str  = os.environ.get("SENHUB_DB_URL", "")

# DB_URL が設定されていれば DB モード
USE_DB:      bool = bool(DB_URL)

# コネクションプールのサイズ
DB_POOL_MIN: int  = int(os.environ.get("SENHUB_DB_POOL_MIN", "2"))
DB_POOL_MAX: int  = int(os.environ.get("SENHUB_DB_POOL_MAX", "10"))


# ------------------------------------------------------------------
# デバッグ用: 設定内容を表示
# ------------------------------------------------------------------
def show():
    print("=== Senhub Server Config ===")
    print(f"  HOST      : {HOST}")
    print(f"  PORT      : {PORT}")
    print(f"  DOMAIN    : {DOMAIN}")
    print(f"  USE_TLS   : {USE_TLS}")
    if USE_TLS:
        print(f"  TLS_CERT  : {TLS_CERT}")
        print(f"  TLS_KEY   : {TLS_KEY}")
    print(f"  MAX_RECS  : {MAX_RECORDS}")
    if CHANNELS_FILE_LOADED:
        print(f"  CHANNELS  : {len(CHANNELS)} チャンネル登録済み"
              f" (ch{min(CHANNELS)}〜ch{max(CHANNELS)})")
    else:
        print(f"  CHANNELS  : channels.yaml なし（開発モード: デフォルトキー使用）")
    if USE_DB:
        # パスワード部分をマスク
        masked = DB_URL
        try:
            from urllib.parse import urlparse, urlunparse
            p = urlparse(DB_URL)
            if p.password:
                masked = DB_URL.replace(p.password, "****")
        except Exception:
            pass
        print(f"  DB_URL    : {masked}")
        print(f"  DB_POOL   : {DB_POOL_MIN}〜{DB_POOL_MAX}")
    else:
        print(f"  DB        : メモリモード（SENHUB_DB_URL 未設定）")
    print("============================")


if __name__ == "__main__":
    show()
