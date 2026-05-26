#!/bin/bash
# =============================================================================
# Senhub ローカルサーバー セットアップスクリプト
# 構成A: Docker Compose（TimescaleDB + Grafana）
#
# 動作環境: Ubuntu 24.04 LTS (root 実行)
#
# 使い方（開発機から）:
#   rsync -av --exclude='__pycache__' --exclude='*.pyc' \
#     /workspaces/example/ root@SERVER_IP:/tmp/senhub-src/
#   ssh root@SERVER_IP "bash /tmp/senhub-src/scripts/install-local.sh"
#
# 冪等: 2回目以降の実行も安全（既存設定は上書きしない）
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
# パス定義
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="/opt/senhub"
SERVICE_FILE="/etc/systemd/system/senhub.service"

# DB / Grafana 固定設定
DB_USER="senhub"
DB_NAME="senhub"
GRAFANA_ADMIN="admin"
CREDS_FILE="$INSTALL_DIR/CREDENTIALS.txt"

# パスワード: 既存の CREDENTIALS.txt があれば再利用、なければランダム生成
if [[ -f "$CREDS_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$CREDS_FILE"
    echo -e "  既存の認証情報を読み込みました: $CREDS_FILE"
else
    # openssl がなければ /dev/urandom で代替
    _rand() { openssl rand -hex "$1" 2>/dev/null || head -c "$1" /dev/urandom | xxd -p | tr -d '\n'; }
    DB_PASS="${SENHUB_DB_PASS:-$(_rand 16)}"
    GRAFANA_PASS="${SENHUB_GRAFANA_PASS:-$(_rand 12)}"
fi

# =============================================================================
# STEP 0: 事前チェック
# =============================================================================
step "0/9" "事前チェック"

[[ $EUID -eq 0 ]] || err "このスクリプトは root で実行してください (sudo bash $0)"

# Ubuntu 確認（警告のみ）
if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    if [[ "$ID" != "ubuntu" ]]; then
        warn "Ubuntu 以外の OS です: $PRETTY_NAME（動作未確認）"
    elif [[ "$VERSION_ID" != "24.04" ]]; then
        warn "Ubuntu $VERSION_ID で実行中（動作確認済み: 24.04）"
    fi
fi

# リポジトリファイル確認
[[ -f "$REPO_DIR/server/main.py" ]]          || err "server/main.py が見つかりません: $REPO_DIR"
[[ -f "$REPO_DIR/server/schema.sql" ]]       || err "server/schema.sql が見つかりません"
[[ -f "$REPO_DIR/server/requirements.txt" ]] || err "server/requirements.txt が見つかりません"

ok "チェック完了 (リポジトリ: $REPO_DIR)"

# =============================================================================
# STEP 1: パッケージインストール
# =============================================================================
step "1/9" "パッケージインストール"

apt-get update -qq
apt-get install -y -qq git python3-pip python3-venv curl ca-certificates gnupg
ok "基本パッケージ インストール完了"

# Docker がなければインストール
if ! command -v docker &>/dev/null; then
    info "Docker CE をインストール中..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    # アーキテクチャを自動検出
    ARCH=$(dpkg --print-architecture)
    # shellcheck disable=SC1091
    CODENAME=$(source /etc/os-release && echo "$VERSION_CODENAME")
    echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    ok "Docker インストール完了"
else
    ok "Docker は既にインストール済み ($(docker --version | cut -d' ' -f3 | tr -d ','))"
fi

# docker compose plugin の確認
docker compose version &>/dev/null || err "docker compose plugin が使えません"
ok "Docker Compose 利用可能"

# =============================================================================
# STEP 2: ディレクトリ構造の作成
# =============================================================================
step "2/9" "ディレクトリ構造の作成"

mkdir -p \
    "$INSTALL_DIR/server" \
    "$INSTALL_DIR/scripts" \
    "$INSTALL_DIR/grafana/provisioning/datasources" \
    "$INSTALL_DIR/grafana/provisioning/dashboards"

ok "ディレクトリ作成完了: $INSTALL_DIR/"

# =============================================================================
# STEP 3: サーバーファイルのコピー
# =============================================================================
step "3/9" "サーバーファイルのコピー"

cp "$REPO_DIR/server/main.py"              "$INSTALL_DIR/server/"
cp "$REPO_DIR/server/db.py"                "$INSTALL_DIR/server/" 2>/dev/null || warn "db.py が見つかりません（メモリモードで動作）"
cp "$REPO_DIR/server/config.py"            "$INSTALL_DIR/server/"
cp "$REPO_DIR/server/requirements.txt"     "$INSTALL_DIR/server/"
cp "$REPO_DIR/server/schema.sql"           "$INSTALL_DIR/server/"
cp "$REPO_DIR/server/channels.yaml.example" "$INSTALL_DIR/server/" 2>/dev/null || warn "channels.yaml.example が見つかりません"
cp "$REPO_DIR/scripts/monitor.py"          "$INSTALL_DIR/scripts/" 2>/dev/null || warn "monitor.py が見つかりません"
cp "$REPO_DIR/scripts/gen-channel-keys.py" "$INSTALL_DIR/scripts/" 2>/dev/null || warn "gen-channel-keys.py が見つかりません"

ok "サーバーファイルのコピー完了"

# =============================================================================
# STEP 4: 設定ファイルの生成
# =============================================================================
step "4/9" "設定ファイルの生成"

# ---- docker-compose.yml ----
cat > "$INSTALL_DIR/docker-compose.yml" << EOF
networks:
  senhub-net:
    name: senhub-net

volumes:
  timescaledb-data:
  grafana-data:

services:
  timescaledb:
    image: timescale/timescaledb:latest-pg16
    container_name: senhub-timescaledb
    restart: unless-stopped
    networks:
      - senhub-net
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASS}
      POSTGRES_DB: ${DB_NAME}
    volumes:
      - timescaledb-data:/var/lib/postgresql/data

  grafana:
    image: grafana/grafana:latest
    container_name: senhub-grafana
    restart: unless-stopped
    networks:
      - senhub-net
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASS}
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - grafana-data:/var/lib/grafana
      - ${INSTALL_DIR}/grafana/provisioning:/etc/grafana/provisioning
EOF
ok "docker-compose.yml 作成完了"

# ---- Grafana データソース（コメントなし: Grafanaのパース問題を回避）----
cat > "$INSTALL_DIR/grafana/provisioning/datasources/timescaledb.yaml" << EOF
apiVersion: 1

datasources:
  - name: TimescaleDB
    type: grafana-postgresql-datasource
    access: proxy
    url: senhub-timescaledb:5432
    database: ${DB_NAME}
    user: ${DB_USER}
    secureJsonData:
      password: ${DB_PASS}
    jsonData:
      sslmode: disable
      postgresVersion: 1600
      timescaledb: true
    isDefault: true
    editable: true
EOF
ok "Grafana データソース設定 作成完了"

# ---- Grafana ダッシュボードプロバイダー ----
if [[ ! -f "$INSTALL_DIR/grafana/provisioning/dashboards/provider.yaml" ]]; then
    cat > "$INSTALL_DIR/grafana/provisioning/dashboards/provider.yaml" << 'EOF'
apiVersion: 1

providers:
  - name: senhub
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: true
    options:
      path: /etc/grafana/provisioning/dashboards
      foldersFromFilesStructure: true
EOF
    ok "Grafana ダッシュボードプロバイダー 作成完了"
else
    ok "Grafana ダッシュボードプロバイダー は既に存在（スキップ）"
fi

# ---- リポジトリの Grafana JSON をコピー（存在する場合）----
if ls "$REPO_DIR/grafana/provisioning/dashboards/"*.json &>/dev/null 2>&1; then
    cp "$REPO_DIR/grafana/provisioning/dashboards/"*.json \
       "$INSTALL_DIR/grafana/provisioning/dashboards/" 2>/dev/null || true
    ok "Grafana ダッシュボード JSON をコピー"
fi

# =============================================================================
# STEP 5: Python 仮想環境
# =============================================================================
step "5/9" "Python 仮想環境のセットアップ"

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
step "6/9" "channels.yaml と .env の生成"

# channels.yaml（既存なら上書きしない）
if [[ ! -f "$INSTALL_DIR/server/channels.yaml" ]]; then
    if [[ -f "$INSTALL_DIR/server/channels.yaml.example" ]]; then
        cp "$INSTALL_DIR/server/channels.yaml.example" "$INSTALL_DIR/server/channels.yaml"
        chmod 600 "$INSTALL_DIR/server/channels.yaml"
        ok "channels.yaml を example から作成"
        warn "本番運用前に channels.yaml のキーを変更してください"
    else
        warn "channels.yaml.example が見つかりません。channels.yaml は手動で作成してください"
    fi
else
    ok "channels.yaml は既に存在（スキップ）"
fi

# .env（既存なら上書きしない）
if [[ ! -f "$INSTALL_DIR/server/.env" ]]; then
    cat > "$INSTALL_DIR/server/.env" << EOF
SENHUB_PORT=8000
SENHUB_USE_TLS=false
SENHUB_DB_URL=postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}
EOF
    chmod 600 "$INSTALL_DIR/server/.env"
    ok ".env 作成完了"
else
    ok ".env は既に存在（スキップ）"
fi

# 認証情報を CREDENTIALS.txt に保存（再インストール時に同じパスワードを使えるよう）
cat > "$CREDS_FILE" << EOF
# Senhub 認証情報 (自動生成) — chmod 600 で保護
DB_PASS="${DB_PASS}"
GRAFANA_PASS="${GRAFANA_PASS}"
EOF
chmod 600 "$CREDS_FILE"
ok "認証情報を保存: $CREDS_FILE (chmod 600)"

# =============================================================================
# STEP 7: systemd サービス登録
# =============================================================================
step "7/9" "systemd サービス登録"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Senhub IoT Data Server
After=network.target docker.service
Requires=docker.service

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
ok "systemd サービス登録完了 (senhub.service)"

# =============================================================================
# STEP 8: Docker Compose 起動 & DBスキーマ適用
# =============================================================================
step "8/9" "Docker Compose 起動 & DBスキーマ適用"

cd "$INSTALL_DIR"
docker compose up -d
ok "コンテナ起動完了"

# TimescaleDB が起動するまで待機
info "TimescaleDB の起動を待機中..."
MAX_WAIT=60
WAITED=0
while ! docker exec senhub-timescaledb pg_isready -U "$DB_USER" -d "$DB_NAME" -q 2>/dev/null; do
    sleep 2
    WAITED=$((WAITED + 2))
    if [[ $WAITED -ge $MAX_WAIT ]]; then
        err "TimescaleDB の起動がタイムアウト（${MAX_WAIT}秒）。ログを確認: docker compose logs timescaledb"
    fi
done
ok "TimescaleDB 起動確認 (${WAITED}秒待機)"

# スキーマ適用
docker exec -i senhub-timescaledb \
    psql -U "$DB_USER" -d "$DB_NAME" < "$INSTALL_DIR/server/schema.sql" > /dev/null 2>&1
ok "DBスキーマ適用完了"

# senhub サービス起動
systemctl start senhub
sleep 3
ok "senhub サービス起動完了"

# =============================================================================
# STEP 9: ヘルスチェック
# =============================================================================
step "9/9" "ヘルスチェック"

# Senhub API
SENHUB_OK=false
for i in 1 2 3 4 5; do
    if curl -sf "http://localhost:8000/api/v1/channels/100/data?readKey=test_readKey" > /dev/null 2>&1; then
        SENHUB_OK=true
        break
    fi
    sleep 2
done

if $SENHUB_OK; then
    ok "Senhub API: 正常応答"
else
    warn "Senhub API: 応答なし（ログ確認: journalctl -u senhub -n 50）"
fi

# Grafana
GRAFANA_OK=false
for i in 1 2 3 4 5; do
    if curl -sf "http://localhost:3000/api/health" > /dev/null 2>&1; then
        GRAFANA_OK=true
        break
    fi
    sleep 3
done

if $GRAFANA_OK; then
    ok "Grafana: 正常応答"
else
    warn "Grafana: 起動中の可能性あり（しばらく待ってブラウザでアクセスしてください）"
fi

# =============================================================================
# 完了サマリー
# =============================================================================
SERVER_IP=$(hostname -I | awk '{print $1}')

echo ""
echo -e "${BOLD}======================================================${NC}"
echo -e "${BOLD}  Senhub セットアップ完了！${NC}"
echo -e "${BOLD}======================================================${NC}"
echo ""
echo -e "  ${CYAN}Senhub API:${NC}  http://${SERVER_IP}:8000"
echo -e "  ${CYAN}Grafana:${NC}     http://${SERVER_IP}:3000"
echo -e "             ユーザー: ${GRAFANA_ADMIN} / パスワード: ${GRAFANA_PASS}"
echo -e "  ${CYAN}認証情報ファイル:${NC} ${CREDS_FILE} (chmod 600)"
echo ""
echo -e "  ${CYAN}テストチャンネル:${NC}"
echo -e "    channelId: 100"
echo -e "    writeKey:  test_writeKey"
echo -e "    readKey:   test_readKey"
echo ""
echo -e "  ${YELLOW}⚠ 本番運用前に channels.yaml のキーを変更してください:${NC}"
echo -e "    ${INSTALL_DIR}/server/channels.yaml"
echo ""
echo -e "  ${CYAN}サービス管理:${NC}"
echo -e "    systemctl status senhub"
echo -e "    journalctl -u senhub -f"
echo -e "    cd ${INSTALL_DIR} && docker compose ps"
echo ""
echo -e "  ${CYAN}リアルタイムモニター:${NC}"
echo -e "    python3 ${INSTALL_DIR}/scripts/monitor.py \\"
echo -e "      --url http://localhost:8000/api/v1 --interval 2"
echo ""
