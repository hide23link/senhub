#!/bin/bash
# =============================================================================
# Senhub 本番サーバー セットアップスクリプト
# 構成B: ベアメタル（TimescaleDB apt + Let's Encrypt）
#
# 動作環境: Ubuntu 24.04 LTS (root 実行)
#
# 使い方:
#   bash scripts/install-production.sh --domain senhub.example.com --email admin@example.com
#   bash scripts/install-production.sh --domain 192.168.1.100 --no-tls   # HTTP専用
#
# オプション:
#   --domain DOMAIN    公開ドメインまたはIPアドレス（必須）
#   --email  EMAIL     Let's Encrypt 用メールアドレス（TLS使用時に必須）
#   --no-tls           HTTPS をスキップ（社内 LAN 等）
#   --skip-db          DB 初期化をスキップ（既にセットアップ済みの場合）
#   --port   PORT      リッスンポート（デフォルト: TLS=443, HTTP=8000）
# =============================================================================
set -euo pipefail

# -----------------------------------------------------------------------------
# カラー出力
# -----------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗ エラー:${NC} $*" >&2; exit 1; }
info() { echo -e "  ${CYAN}→${NC} $*"; }
step() { echo -e "\n${BOLD}[$1]${NC} $2"; }

# -----------------------------------------------------------------------------
# 引数パース
# -----------------------------------------------------------------------------
DOMAIN=""
EMAIL=""
USE_TLS=true
SKIP_DB=false
CUSTOM_PORT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain) DOMAIN="$2"; shift 2 ;;
        --email)  EMAIL="$2";  shift 2 ;;
        --no-tls) USE_TLS=false; shift ;;
        --skip-db) SKIP_DB=true; shift ;;
        --port)   CUSTOM_PORT="$2"; shift 2 ;;
        -h|--help)
            echo "使い方: $0 --domain DOMAIN [--email EMAIL] [--no-tls] [--skip-db] [--port PORT]"
            exit 0
            ;;
        *) err "不明なオプション: $1 (--help でヘルプを表示)" ;;
    esac
done

# ポートのデフォルト値
if [[ -n "$CUSTOM_PORT" ]]; then
    PORT="$CUSTOM_PORT"
elif $USE_TLS; then
    PORT=443
else
    PORT=8000
fi

# -----------------------------------------------------------------------------
# パス定義
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="/opt/senhub"
SERVICE_FILE="/etc/systemd/system/senhub.service"
PG_CONF="/etc/postgresql/16/main/postgresql.conf"
PG_HBA="/etc/postgresql/16/main/pg_hba.conf"

# DB 認証情報
DB_USER="senhub"
DB_PASS="senhubpass"
DB_NAME="senhub"

# =============================================================================
# STEP 0: 事前チェック
# =============================================================================
step "0/8" "事前チェック"

[[ $EUID -eq 0 ]] || err "このスクリプトは root で実行してください (sudo bash $0)"
[[ -n "$DOMAIN" ]] || err "--domain が指定されていません"
if $USE_TLS && [[ -z "$EMAIL" ]]; then
    warn "--email が指定されていません。Let's Encrypt 証明書取得はスキップされます"
    warn "後から取得する場合: certbot certonly --standalone -d $DOMAIN --email your@email.com --agree-tos"
fi

if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    if [[ "$ID" != "ubuntu" ]]; then
        warn "Ubuntu 以外の OS です: $PRETTY_NAME（動作未確認）"
    elif [[ "$VERSION_ID" != "24.04" ]]; then
        warn "Ubuntu $VERSION_ID で実行中（動作確認済み: 24.04）"
    fi
fi

[[ -f "$REPO_DIR/server/main.py" ]]          || err "server/main.py が見つかりません: $REPO_DIR"
[[ -f "$REPO_DIR/server/schema.sql" ]]       || err "server/schema.sql が見つかりません"
[[ -f "$REPO_DIR/server/requirements.txt" ]] || err "server/requirements.txt が見つかりません"

ok "チェック完了 (ドメイン: $DOMAIN, TLS: $USE_TLS, ポート: $PORT)"

# =============================================================================
# STEP 1: パッケージインストール
# =============================================================================
step "1/8" "パッケージインストール"

apt-get update -qq
apt-get install -y -qq python3-pip python3-venv curl ca-certificates gnupg
ok "基本パッケージ インストール完了"

# =============================================================================
# STEP 2: TimescaleDB インストール
# =============================================================================
step "2/8" "TimescaleDB インストール"

if dpkg -l timescaledb-2-postgresql-16 &>/dev/null 2>&1; then
    ok "TimescaleDB は既にインストール済み（スキップ）"
else
    info "TimescaleDB リポジトリを登録中..."
    curl -fsSL https://packagecloud.io/timescale/timescaledb/gpgkey \
        | gpg --dearmor -o /usr/share/keyrings/timescaledb.gpg

    echo 'deb [signed-by=/usr/share/keyrings/timescaledb.gpg] \
https://packagecloud.io/timescale/timescaledb/ubuntu/ noble main' \
        > /etc/apt/sources.list.d/timescaledb.list

    apt-get update -qq
    apt-get install -y -qq timescaledb-2-postgresql-16 postgresql-client-16
    ok "TimescaleDB インストール完了"
fi

# postgresql.conf に shared_preload_libraries を追加
if [[ -f "$PG_CONF" ]]; then
    if ! grep -q "^shared_preload_libraries.*timescaledb" "$PG_CONF"; then
        sed -i "s/#shared_preload_libraries = ''/shared_preload_libraries = 'timescaledb'/" "$PG_CONF"
        ok "postgresql.conf: shared_preload_libraries 追加"
    else
        ok "postgresql.conf: shared_preload_libraries は設定済み"
    fi
fi

# PostgreSQL 起動
systemctl enable postgresql
systemctl start postgresql
sleep 3
ok "PostgreSQL 起動確認"

# =============================================================================
# STEP 3: DB セットアップ
# =============================================================================
step "3/8" "DB セットアップ"

if $SKIP_DB; then
    warn "DB セットアップをスキップ（--skip-db が指定されています）"
else
    # pg_hba.conf を一時的に trust に変更してユーザー作成
    if grep -q "^local.*postgres.*peer" "$PG_HBA" 2>/dev/null; then
        sed -i 's/^local   all             postgres                                peer/local   all             postgres                                trust/' "$PG_HBA"
        systemctl reload postgresql
        PG_HBA_MODIFIED=true
    else
        PG_HBA_MODIFIED=false
    fi

    # ユーザー作成（既存なら SKIP）
    if ! psql -U postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1; then
        psql -U postgres -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';" > /dev/null
        ok "DB ユーザー作成: ${DB_USER}"
    else
        ok "DB ユーザーは既に存在: ${DB_USER}（スキップ）"
    fi

    # DB 作成（既存なら SKIP）
    if ! psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
        psql -U postgres -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" > /dev/null
        ok "DB 作成: ${DB_NAME}"
    else
        ok "DB は既に存在: ${DB_NAME}（スキップ）"
    fi

    # TimescaleDB 拡張
    psql -U postgres -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;" > /dev/null
    ok "TimescaleDB 拡張 有効化"

    # pg_hba.conf を元に戻す
    if $PG_HBA_MODIFIED; then
        sed -i 's/^local   all             postgres                                trust/local   all             postgres                                peer/' "$PG_HBA"
        systemctl reload postgresql
    fi

    # スキーマ適用
    PGPASSWORD="$DB_PASS" psql -U "$DB_USER" -d "$DB_NAME" -h 127.0.0.1 \
        -f "$REPO_DIR/server/schema.sql" > /dev/null 2>&1
    ok "DBスキーマ適用完了"
fi

# =============================================================================
# STEP 4: ファイルのコピー
# =============================================================================
step "4/8" "サーバーファイルのコピー"

mkdir -p "$INSTALL_DIR/server" "$INSTALL_DIR/scripts"

cp "$REPO_DIR/server/main.py"              "$INSTALL_DIR/server/"
cp "$REPO_DIR/server/db.py"                "$INSTALL_DIR/server/" 2>/dev/null || warn "db.py が見つかりません"
cp "$REPO_DIR/server/config.py"            "$INSTALL_DIR/server/"
cp "$REPO_DIR/server/requirements.txt"     "$INSTALL_DIR/server/"
cp "$REPO_DIR/server/schema.sql"           "$INSTALL_DIR/server/"
cp "$REPO_DIR/server/channels.yaml.example" "$INSTALL_DIR/server/" 2>/dev/null || true
cp "$REPO_DIR/scripts/monitor.py"          "$INSTALL_DIR/scripts/" 2>/dev/null || true
cp "$REPO_DIR/scripts/gen-channel-keys.py" "$INSTALL_DIR/scripts/" 2>/dev/null || true

ok "サーバーファイルのコピー完了"

# =============================================================================
# STEP 5: Python 仮想環境
# =============================================================================
step "5/8" "Python 仮想環境のセットアップ"

if [[ ! -d "$INSTALL_DIR/venv" ]]; then
    python3 -m venv "$INSTALL_DIR/venv"
    ok "仮想環境を作成: $INSTALL_DIR/venv"
else
    ok "仮想環境は既に存在（スキップ）"
fi

info "pip install 中..."
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/server/requirements.txt"
ok "Python 依存パッケージ インストール完了"

# =============================================================================
# STEP 6: channels.yaml と .env の生成
# =============================================================================
step "6/8" "channels.yaml と .env の生成"

# channels.yaml（既存なら上書きしない）
if [[ ! -f "$INSTALL_DIR/server/channels.yaml" ]]; then
    if [[ -f "$INSTALL_DIR/server/channels.yaml.example" ]]; then
        cp "$INSTALL_DIR/server/channels.yaml.example" "$INSTALL_DIR/server/channels.yaml"
        chmod 600 "$INSTALL_DIR/server/channels.yaml"
        ok "channels.yaml を example から作成"
        warn "本番運用前に channels.yaml のキーを変更してください"
    else
        warn "channels.yaml.example がありません。手動で作成してください"
    fi
else
    ok "channels.yaml は既に存在（スキップ）"
fi

# .env（既存なら上書きしない）
if [[ ! -f "$INSTALL_DIR/server/.env" ]]; then
    if $USE_TLS; then
        cat > "$INSTALL_DIR/server/.env" << EOF
SENHUB_USE_TLS=false
SENHUB_PORT=8000
SENHUB_DB_URL=postgresql://${DB_USER}:${DB_PASS}@127.0.0.1:5432/${DB_NAME}
EOF
        # TLS が有効でも、証明書取得前は HTTP で起動する
        info "初回は HTTP モード（証明書取得後に HTTPS に切り替えます）"
    else
        cat > "$INSTALL_DIR/server/.env" << EOF
SENHUB_USE_TLS=false
SENHUB_PORT=${PORT}
SENHUB_DB_URL=postgresql://${DB_USER}:${DB_PASS}@127.0.0.1:5432/${DB_NAME}
EOF
    fi
    chmod 600 "$INSTALL_DIR/server/.env"
    ok ".env 作成完了"
else
    ok ".env は既に存在（スキップ）"
fi

# =============================================================================
# STEP 7: systemd サービス登録
# =============================================================================
step "7/8" "systemd サービス登録"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Senhub IoT Server
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}/server
EnvironmentFile=${INSTALL_DIR}/server/.env
ExecStart=${INSTALL_DIR}/venv/bin/python main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable senhub
systemctl start senhub
sleep 3
ok "systemd サービス起動完了 (senhub.service)"

# 起動確認
HTTP_PORT=8000
for i in 1 2 3 4 5; do
    if curl -sf "http://localhost:${HTTP_PORT}/api/v1/channels/100/data?readKey=test_readKey" > /dev/null 2>&1; then
        ok "Senhub API: 正常応答（HTTP ポート ${HTTP_PORT}）"
        break
    fi
    sleep 2
done

# =============================================================================
# STEP 8: Let's Encrypt 証明書取得（--no-tls でない場合）
# =============================================================================
step "8/8" "HTTPS 設定"

if ! $USE_TLS; then
    ok "HTTP モードで動作（--no-tls 指定）"
else
    CERT_PATH="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"

    if [[ -f "$CERT_PATH" ]]; then
        ok "証明書は既に存在: $CERT_PATH（スキップ）"
        # .env を HTTPS に更新
        cat > "$INSTALL_DIR/server/.env" << EOF
SENHUB_USE_TLS=true
SENHUB_PORT=${PORT}
SENHUB_DOMAIN=${DOMAIN}
SENHUB_DB_URL=postgresql://${DB_USER}:${DB_PASS}@127.0.0.1:5432/${DB_NAME}
EOF
        systemctl restart senhub
        ok ".env を HTTPS モードに更新"

    elif [[ -n "$EMAIL" ]]; then
        info "certbot をインストール中..."
        apt-get install -y -qq certbot

        info "port 80 を一時的に開放（UFW が有効な場合）..."
        ufw allow 80/tcp 2>/dev/null || true

        # senhub を一時停止（certbot standalone がポート使用）
        systemctl stop senhub

        certbot certonly \
            --standalone \
            --non-interactive \
            --agree-tos \
            --email "$EMAIL" \
            -d "$DOMAIN" \
            || err "証明書取得に失敗しました。DNS が正しく設定されているか、ポート80が開放されているか確認してください"

        ok "Let's Encrypt 証明書取得完了"

        # .env を HTTPS に更新
        cat > "$INSTALL_DIR/server/.env" << EOF
SENHUB_USE_TLS=true
SENHUB_PORT=${PORT}
SENHUB_DOMAIN=${DOMAIN}
SENHUB_DB_URL=postgresql://${DB_USER}:${DB_PASS}@127.0.0.1:5432/${DB_NAME}
EOF
        chmod 600 "$INSTALL_DIR/server/.env"

        # ファイアウォール設定
        ufw allow "${PORT}/tcp" 2>/dev/null || true

        systemctl start senhub
        sleep 3
        ok ".env を HTTPS モードに更新、サービス再起動完了"

    else
        warn "証明書取得をスキップ（--email が指定されていません）"
        warn "後から取得する場合:"
        warn "  apt-get install -y certbot"
        warn "  certbot certonly --standalone --email YOUR_EMAIL --agree-tos -d ${DOMAIN}"
        warn "  # .env に SENHUB_USE_TLS=true, SENHUB_PORT=${PORT}, SENHUB_DOMAIN=${DOMAIN} を設定"
        warn "  systemctl restart senhub"
    fi
fi

# =============================================================================
# 完了サマリー
# =============================================================================
echo ""
echo -e "${BOLD}======================================================${NC}"
echo -e "${BOLD}  Senhub 本番サーバー セットアップ完了！${NC}"
echo -e "${BOLD}======================================================${NC}"
echo ""
if $USE_TLS && [[ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
    echo -e "  ${CYAN}Senhub API:${NC}  https://${DOMAIN}"
else
    echo -e "  ${CYAN}Senhub API:${NC}  http://${DOMAIN}:${PORT}"
fi
echo ""
echo -e "  ${CYAN}テストチャンネル:${NC}"
echo -e "    channelId: 100 / writeKey: test_writeKey / readKey: test_readKey"
echo ""
echo -e "  ${YELLOW}⚠ 本番運用前に channels.yaml のキーを変更してください:${NC}"
echo -e "    ${INSTALL_DIR}/server/channels.yaml"
echo ""
echo -e "  ${CYAN}サービス管理:${NC}"
echo -e "    systemctl status senhub"
echo -e "    journalctl -u senhub -f"
echo ""
echo -e "  ${CYAN}リアルタイムモニター:${NC}"
if $USE_TLS && [[ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
    echo -e "    python3 ${INSTALL_DIR}/scripts/monitor.py \\"
    echo -e "      --url https://${DOMAIN}/api/v1 --interval 2"
else
    echo -e "    python3 ${INSTALL_DIR}/scripts/monitor.py \\"
    echo -e "      --url http://${DOMAIN}:${PORT}/api/v1 --interval 2"
fi
echo ""
