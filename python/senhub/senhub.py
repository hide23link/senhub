"""
Senhub Python ライブラリ
仕様書: senhub_ライブラリ仕様書.md

接続先の変更方法（優先順位順）:
  1. Senhub(channelId, writeKey, base_url="https://myserver.com/api/v1")  # インスタンス引数
  2. 環境変数 SENHUB_BASE_URL=https://myserver.com/api/v1                  # プロセス全体
  3. デフォルト値 https://senhub.hide.link/api/v1                          # フォールバック
"""
import os
import requests
from datetime import date as _date

# 環境変数 SENHUB_BASE_URL が設定されていればそちらを使用
BASE_URL = os.environ.get("SENHUB_BASE_URL", "https://senhub.hide.link/api/v1")
VALID_FIELDS = {f"d{i}" for i in range(1, 9)}


class SenhubAuthError(Exception):
    """writeKey / readKey 不正"""
    pass


class SenhubTimeoutError(Exception):
    """サーバー応答タイムアウト"""
    pass


class SenhubValueError(Exception):
    """引数の値が不正"""
    pass


class Senhub:
    def __init__(
        self,
        channelId: int,
        writeKey: str,
        readKey: str = "",
        base_url: str = None,
    ):
        """
        初期化

        Args:
            channelId: チャネルID
            writeKey:  書き込みキー
            readKey:   読み込みキー（read / export 使用時は必須）
            base_url:  接続先URL（テスト時に変更可。デフォルト: senhub.hide.link）
        """
        self._channel_id = channelId
        self._write_key  = writeKey
        self._read_key   = readKey
        self._base       = f"{base_url or BASE_URL}/channels/{channelId}"

    # ------------------------------------------------------------------
    # データ送信
    # ------------------------------------------------------------------
    def send(self, data: dict) -> int:
        """
        センサー値または機器状態（0/1）を送信する

        Args:
            data: {"d1": value, ...}  キーは "d1"〜"d8"

        Returns:
            HTTPステータスコード（200 = 成功）

        Raises:
            SenhubValueError:   不正なフィールド名
            SenhubAuthError:    writeKey 不正
            SenhubTimeoutError: タイムアウト
        """
        for key in data:
            if key not in VALID_FIELDS:
                raise SenhubValueError(f"無効なフィールド名: '{key}'  (d1〜d8 を指定してください)")

        params = {"writeKey": self._write_key}
        params.update({k: str(v) for k, v in data.items()})

        try:
            r = requests.get(f"{self._base}/data", params=params, timeout=10)
        except requests.Timeout:
            raise SenhubTimeoutError("サーバーがタイムアウトしました")
        except requests.ConnectionError as e:
            raise ConnectionError(f"サーバーに接続できません: {e}")

        if r.status_code == 401:
            raise SenhubAuthError("writeKey が不正です")

        return r.status_code

    # ------------------------------------------------------------------
    # データ取得
    # ------------------------------------------------------------------
    def read(
        self,
        n: int = None,
        date: str = None,
        start: str = None,
        end: str = None,
        resolution: str = "raw",
    ) -> list:
        """
        センサーデータを取得する

        Args:
            n:          最新N件（最大3000）
            date:       日付指定 "YYYY-MM-DD"
            start:      開始日時 "YYYY-MM-DD HH:MM:SS"
            end:        終了日時 "YYYY-MM-DD HH:MM:SS"
            resolution: "raw" / "1min" / "1hour"

        Returns:
            [{"created": "...", "d1": 23.5, ...}, ...]

        Raises:
            SenhubAuthError:    readKey 不正
            SenhubTimeoutError: タイムアウト
        """
        if not self._read_key:
            raise SenhubAuthError("read() には readKey が必要です")

        params = {"readKey": self._read_key}
        if n          is not None: params["n"]          = n
        if date       is not None: params["date"]       = date
        if start      is not None: params["start"]      = start
        if end        is not None: params["end"]        = end
        if resolution != "raw":    params["resolution"] = resolution

        try:
            r = requests.get(f"{self._base}/data", params=params, timeout=10)
        except requests.Timeout:
            raise SenhubTimeoutError("サーバーがタイムアウトしました")
        except requests.ConnectionError as e:
            raise ConnectionError(f"サーバーに接続できません: {e}")

        if r.status_code == 401:
            raise SenhubAuthError("readKey が不正です")

        return self._parse_csv(r.text)

    # ------------------------------------------------------------------
    # データエクスポート
    # ------------------------------------------------------------------
    def export(
        self,
        format: str = "csv",
        start: str = None,
        end: str = None,
    ) -> str:
        """
        データをエクスポートする

        Args:
            format: "csv" / "json"
            start:  開始日時 "YYYY-MM-DD HH:MM:SS"
            end:    終了日時 "YYYY-MM-DD HH:MM:SS"

        Returns:
            CSV文字列 または JSON文字列

        Raises:
            SenhubAuthError:    readKey 不正
            SenhubTimeoutError: タイムアウト
        """
        if not self._read_key:
            raise SenhubAuthError("export() には readKey が必要です")

        params = {"readKey": self._read_key, "format": format}
        if start is not None: params["start"] = start
        if end   is not None: params["end"]   = end

        try:
            r = requests.get(f"{self._base}/export", params=params, timeout=30)
        except requests.Timeout:
            raise SenhubTimeoutError("サーバーがタイムアウトしました")
        except requests.ConnectionError as e:
            raise ConnectionError(f"サーバーに接続できません: {e}")

        if r.status_code == 401:
            raise SenhubAuthError("readKey が不正です")

        return r.text

    # ------------------------------------------------------------------
    # チャネル設定
    # ------------------------------------------------------------------
    def getprop(self) -> dict:
        """
        チャネル設定を取得する

        Returns:
            {
                "channelId": 100,
                "d1": {"name": "温度", "unit": "℃", "type": "sensor"},
                ...
            }
        """
        params = {}
        if self._read_key:
            params["readKey"] = self._read_key

        try:
            r = requests.get(f"{self._base}/properties", params=params, timeout=10)
        except requests.Timeout:
            raise SenhubTimeoutError("サーバーがタイムアウトしました")
        except requests.ConnectionError as e:
            raise ConnectionError(f"サーバーに接続できません: {e}")

        return self._parse_properties(r.text)

    def setprop(self, properties: dict) -> bool:
        """
        チャネル設定を更新する

        Args:
            properties: {
                "d1": {"name": "温度", "unit": "℃", "type": "sensor"},
                ...
            }
            type は "sensor"（連続値）または "event"（ON/OFF）

        Returns:
            True（成功） / False（失敗）
        """
        lines = []
        for field, attrs in properties.items():
            if field not in VALID_FIELDS:
                raise SenhubValueError(f"無効なフィールド名: '{field}'")
            for attr, val in attrs.items():
                lines.append(f"{field}.{attr}={val}")
        body = "\n".join(lines)

        try:
            r = requests.post(
                f"{self._base}/properties",
                params={"writeKey": self._write_key},
                data=body.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
                timeout=10,
            )
        except requests.Timeout:
            raise SenhubTimeoutError("サーバーがタイムアウトしました")
        except requests.ConnectionError as e:
            raise ConnectionError(f"サーバーに接続できません: {e}")

        if r.status_code == 401:
            raise SenhubAuthError("writeKey が不正です")

        return r.status_code == 200

    # ------------------------------------------------------------------
    # 内部ユーティリティ
    # ------------------------------------------------------------------
    def _parse_csv(self, text: str) -> list:
        """
        CSV レスポンスを dict のリストに変換する
        行フォーマット: created,d1,d2,d3,d4,d5,d6,d7,d8
        """
        result = []
        fields = ["d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8"]

        for line in text.strip().split("\n"):
            if not line or line.startswith("created"):
                continue  # ヘッダー行またはスキップ
            parts = line.split(",")
            if len(parts) < 2:
                continue
            row = {"created": parts[0]}
            for i, field in enumerate(fields, start=1):
                if i < len(parts) and parts[i] != "":
                    try:
                        row[field] = float(parts[i])
                    except ValueError:
                        row[field] = parts[i]
            result.append(row)

        return result

    def _parse_properties(self, text: str) -> dict:
        """
        テキストレスポンスを設定 dict に変換する
        形式: key=value  または  d1.name=温度
        """
        result = {}
        for line in text.strip().split("\n"):
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()

            if "." in k:
                field, attr = k.split(".", 1)
                if field not in result:
                    result[field] = {}
                result[field][attr] = v
            else:
                try:
                    result[k] = int(v)
                except ValueError:
                    result[k] = v

        return result
