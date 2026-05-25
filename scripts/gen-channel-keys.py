#!/usr/bin/env python3
"""
Senhub チャンネルキー生成スクリプト

使い方:
    python scripts/gen-channel-keys.py <channel_id> [チャンネル名]

例:
    python scripts/gen-channel-keys.py 101 "製造ライン1"
    python scripts/gen-channel-keys.py 102

出力:
    server/channels.yaml に追記するためのYAMLスニペットを表示します。
    コピーして channels.yaml の channels: セクションに貼り付けてください。

注意:
    最大チャンネル数: 100
    既存チャンネルのキーは変更されません（表示のみ）。
"""
import sys
import secrets

MAX_CHANNELS = 100


def gen_key(prefix: str) -> str:
    """プレフィックス付きランダムキーを生成 (例: w_3f8a2b9d1c4e7f0a5b6c8d2e)"""
    return f"{prefix}_{secrets.token_hex(12)}"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    try:
        channel_id = int(sys.argv[1])
    except ValueError:
        print(f"エラー: channel_id は整数で指定してください（例: 101）", file=sys.stderr)
        sys.exit(1)

    if not (1 <= channel_id <= 65535):
        print(f"エラー: channel_id は 1〜65535 の範囲で指定してください", file=sys.stderr)
        sys.exit(1)

    name = sys.argv[2] if len(sys.argv) >= 3 else f"チャンネル{channel_id}"

    write_key = gen_key("w")
    read_key  = gen_key("r")

    print(f"""
# ---- 以下を server/channels.yaml の channels: セクションに追記 ----
  {channel_id}:
    name: "{name}"
    write_key: "{write_key}"
    read_key:  "{read_key}"
# ---------------------------------------------------------------
""")

    print(f"  channel_id : {channel_id}")
    print(f"  name       : {name}")
    print(f"  write_key  : {write_key}")
    print(f"  read_key   : {read_key}")
    print()
    print("ESP32 Arduino スケッチ用:")
    print(f'  const unsigned int CHANNEL_ID = {channel_id};')
    print(f'  const char* WRITE_KEY = "{write_key}";')
    print()
    print("Python ライブラリ用:")
    print(f'  s = senhub.Senhub({channel_id}, "{write_key}", readKey="{read_key}")')


if __name__ == "__main__":
    main()
