/**
 * Senhub Arduino (ESP32) ライブラリ
 * 仕様書: senhub_ライブラリ仕様書.md
 *
 * 対応ボード: ESP32
 * 依存ライブラリ: WiFiClientSecure (ESP32標準), HTTPClient (ESP32標準)
 */
#pragma once

#include <Arduino.h>
#include <WiFiClient.h>
#include <HTTPClient.h>

// ライブラリ定数（.ino でオーバーライド可）
#ifndef SENHUB_BATCH_SIZE
  #define SENHUB_BATCH_SIZE     10          // バッチ送信件数
#endif
#ifndef SENHUB_BATCH_TIMEOUT
  #define SENHUB_BATCH_TIMEOUT  30000UL     // バッチ送信タイムアウト（ms）
#endif
#define SENHUB_MAX_FIELDS       8           // d1〜d8
#define SENHUB_DEFAULT_URL      "https://senhub.example.com/api/v1"

class Senhub {
public:
    Senhub();

    /**
     * 初期化
     * @param channelId チャネルID
     * @param writeKey  書き込みキー
     * @param client    WiFiClient または WiFiClientSecure のポインタ
     * @param baseUrl   接続先URL（テスト時に変更可。省略時: senhub.example.com）
     */
    void begin(
        unsigned int  channelId,
        const char*   writeKey,
        WiFiClient*   client,
        const char*   baseUrl = SENHUB_DEFAULT_URL
    );

    /**
     * センサー値をセットする（送信はしない）
     * @param field フィールド番号 1〜8
     * @param value 値（int / float / char*）
     * @return true: 成功 / false: フィールド番号が範囲外
     */
    bool set(int field, int         value);
    bool set(int field, float       value);
    bool set(int field, const char* value);

    /**
     * バッファに蓄積し、条件を満たしたらHTTP送信する
     * 送信条件: SENHUB_BATCH_SIZE 件 または SENHUB_BATCH_TIMEOUT 経過
     * @return true: バッファ積み込み成功 または 送信成功 / false: 送信失敗
     */
    bool send();

    /**
     * ON/OFF状態をセットする（送信はしない）
     * @param field フィールド番号 1〜8
     * @param state 1（ON）または 0（OFF）
     * @return true: 成功 / false: フィールド番号が範囲外
     */
    bool setEvent(int field, int state);

    /**
     * setEvent() でセットした値を即時HTTP送信する（バッファしない）
     * @return true: 送信成功 / false: 送信失敗
     */
    bool sendEvent();

    /**
     * バッチ送信件数を変更する（デフォルト: SENHUB_BATCH_SIZE）
     * @param size 1〜SENHUB_BATCH_SIZE
     */
    void setBatchSize(int size);

    /**
     * バッチ送信タイムアウトを変更する（デフォルト: SENHUB_BATCH_TIMEOUT）
     * @param ms タイムアウト（ミリ秒）
     */
    void setBatchTimeout(unsigned long ms);

    /**
     * 最後の send() / sendEvent() の HTTP ステータスコードを返す
     * @return ステータスコード（200=成功, 0=未送信または接続失敗）
     */
    int getLastStatus();

private:
    // バッファ1件分
    struct Sample {
        unsigned long ts;
        char  d[SENHUB_MAX_FIELDS][16];
        bool  used[SENHUB_MAX_FIELDS];
    };

    unsigned int  _channelId;
    char          _writeKey[64];
    WiFiClient*   _client;
    String        _baseUrl;

    int           _batchSize;
    unsigned long _batchTimeout;
    int           _lastStatus;

    // センサーバッチバッファ
    Sample        _buf[SENHUB_BATCH_SIZE];
    int           _bufIdx;
    unsigned long _lastSentAt;

    // 現在の set() 値
    char          _curD[SENHUB_MAX_FIELDS][16];
    bool          _curUsed[SENHUB_MAX_FIELDS];

    // イベント用
    int           _eventField;
    int           _eventState;
    bool          _eventReady;

    // 内部メソッド
    bool   _flush();
    bool   _httpPost(const String& endpoint, const String& body);
    String _channelUrl(const String& endpoint);
};
