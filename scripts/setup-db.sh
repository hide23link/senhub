#!/bin/bash
# Senhub TimescaleDB 初期セットアップスクリプト
#
# 実行方法（postgres ユーザー権限が必要）:
#   sudo -u postgres bash scripts/setup-db.sh
#
# または postgres ユーザーで直接:
#   su - postgres
#   bash /path/to/scripts/setup-db.sh

set -e

DB_USER="senhub"
DB_PASS="senhubpass"
DB_NAME="senhub"

echo "=== Senhub DB セットアップ ==="

# ユーザー作成（既存の場合はスキップ）
psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 || \
    psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';"
echo "✓ ユーザー: ${DB_USER}"

# DB作成（既存の場合はスキップ）
psql -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 || \
    psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
echo "✓ データベース: ${DB_NAME}"

# TimescaleDB 拡張
psql -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"
echo "✓ TimescaleDB 拡張を有効化"

# スキーマ適用
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
psql -d "${DB_NAME}" -U "${DB_USER}" -f "${SCRIPT_DIR}/../server/schema.sql"
echo "✓ スキーマ適用完了"

echo ""
echo "=== セットアップ完了 ==="
echo "接続URL: postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}"
echo ""
echo "server/.env に以下を追加:"
echo "  SENHUB_DB_URL=postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}"
echo "  SENHUB_USE_TLS=false"
echo "  SENHUB_PORT=8000"
