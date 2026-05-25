#!/bin/bash
# Senhub Arduino ライブラリ用リリース ZIP を生成する
#
# 使い方:
#   bash scripts/make-arduino-release.sh
#   bash scripts/make-arduino-release.sh 0.1.2    # バージョン指定
#
# 出力:
#   dist/Senhub-<version>.zip
#
# GitHub Release への添付方法:
#   gh release create v<version> dist/Senhub-<version>.zip

set -euo pipefail

# バージョンを library.properties から取得（引数で上書き可）
LIB_DIR="$(cd "$(dirname "$0")/.." && pwd)/arduino/Senhub"
VERSION="${1:-$(grep '^version=' "$LIB_DIR/library.properties" | cut -d= -f2)}"

DIST_DIR="$(cd "$(dirname "$0")/.." && pwd)/dist"
ZIP_NAME="Senhub-${VERSION}.zip"
ZIP_PATH="$DIST_DIR/$ZIP_NAME"

echo "=== Senhub Arduino ライブラリ ZIP 生成 ==="
echo "  バージョン : $VERSION"
echo "  出力先     : $ZIP_PATH"

mkdir -p "$DIST_DIR"

# ZIP 内のルートフォルダ名を Senhub にする（Arduino IDE が要求する形式）
cd "$(dirname "$LIB_DIR")"
zip -r "$ZIP_PATH" "Senhub/" \
    --exclude "Senhub/__pycache__/*" \
    --exclude "Senhub/*.pyc"

echo ""
echo "✅ 生成完了: $ZIP_PATH"
echo ""
echo "GitHub Release に添付するには:"
echo "  gh release create v${VERSION} \"$ZIP_PATH\" --title \"v${VERSION}\" --notes \"\""
echo ""
echo "Arduino IDE でのインストール方法:"
echo "  スケッチ → ライブラリをインクルード → .ZIP形式のライブラリをインストール"
echo "  → $ZIP_NAME を選択"
