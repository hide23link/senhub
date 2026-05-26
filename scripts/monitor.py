#!/usr/bin/env python3
"""
Senhub リアルタイム受信モニター

使い方:
    python3 scripts/monitor.py
    python3 scripts/monitor.py --channel 100 --key your_readKey
    python3 scripts/monitor.py --channel 101 --key your_readKey --url https://senhub.example.com/api/v1
    python3 scripts/monitor.py --interval 1

停止: Ctrl+C
"""

import urllib.request
import time
import sys
import argparse
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description="Senhub リアルタイム受信モニター")
    parser.add_argument("--channel",  "-c", type=int,   default=100,
                        help="チャンネルID (デフォルト: 100)")
    parser.add_argument("--key",      "-k", type=str,   default="test_readKey",
                        help="readKey (デフォルト: test_readKey)")
    parser.add_argument("--url",      "-u", type=str,   default="https://senhub.example.com/api/v1",
                        help="サーバーURL (デフォルト: https://senhub.example.com/api/v1)")
    parser.add_argument("--interval", "-i", type=float, default=2.0,
                        help="ポーリング間隔（秒）(デフォルト: 2)")
    args = parser.parse_args()

    url = f"{args.url}/channels/{args.channel}/data?readKey={args.key}&n=1"

    print("=== Senhub リアルタイム受信モニター (Ctrl+C で停止) ===")
    print(f"URL      : {args.url}/channels/{args.channel}/data")
    print(f"interval : {args.interval}秒")
    print("-" * 60)
    sys.stdout.flush()

    prev_line = None
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                text = r.read().decode().strip()
            lines = [l for l in text.splitlines() if l and not l.startswith("#")]
            if lines:
                last = lines[-1]
                if last != prev_line:
                    prev_line = last
                    now = datetime.now().strftime("%H:%M:%S")
                    parts = last.split(",")
                    ts = parts[0] if parts else "?"
                    vals = [f"d{i}={v}" for i, v in enumerate(parts[1:], 1) if v]
                    print(f"[{now}] {ts}  {' | '.join(vals)}")
                    sys.stdout.flush()
        except KeyboardInterrupt:
            print("\n停止しました。")
            break
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] エラー: {e}")
            sys.stdout.flush()
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
