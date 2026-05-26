/**
 * Senhub サンプルテストプログラム（ESP32）
 *
 * ================================================================
 * 接続先の切り替え方法
 * ================================================================
 *
 * ① ローカルテスト（PC上のサーバー、HTTP）
 *      SERVER_URL = "http://192.168.x.x:8000/api/v1"
 *      USE_TLS    = false
 *      → WiFiClient を使用（証明書不要）
 *
 * ② 社内 LAN サーバー（固定IP、HTTP）
 *      SERVER_URL = "http://192.168.1.100:8000/api/v1"
 *      USE_TLS    = false
 *      → WiFiClient を使用（証明書不要）
 *
 * ③ 本番サーバー HTTPS 443番（標準）
 *      SERVER_URL = "https://senhub.example.com/api/v1"  ← SENHUB_DEFAULT_URL のデフォルト
 *      USE_TLS    = true
 *      → WiFiClientSecure + setCACert(root_ca) を使用
 *
 * ④ 本番サーバー HTTPS 非標準ポート（例: 8443番）
 *      SERVER_URL = "https://myserver.example.com:8443/api/v1"
 *      USE_TLS    = true
 *      → WiFiClientSecure + setCACert(root_ca) を使用
 *
 * ⑤ デフォルト URL を変更（全スケッチに適用）
 *      #include より前に定義:
 *        #define SENHUB_DEFAULT_URL "https://myserver.example.com/api/v1"
 *      → begin() の第4引数を省略してもこの URL が使われる
 * ================================================================
 */

#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>

// ── デフォルト URL を全体で変更したい場合はここで定義 ──
// （コメントアウトすると Senhub.h 内の SENHUB_DEFAULT_URL が使われる）
// #define SENHUB_DEFAULT_URL "https://myserver.example.com/api/v1"

#include "Senhub.h"

// ===== 接続設定 =====
const char* WIFI_SSID      = "YOUR_SSID";
const char* WIFI_PASS      = "YOUR_PASSWORD";
const unsigned int CHANNEL_ID = 100;
const char* WRITE_KEY      = "test_writeKey";

// --- 接続先を選択（USE_TLS に合わせて SERVER_URL を変更）---
#define USE_TLS false   // HTTP: false / HTTPS: true

#if USE_TLS
// ③④ HTTPS 接続: ドメインまたは ドメイン:ポート を指定
const char* SERVER_URL = "https://senhub.example.com/api/v1";
// const char* SERVER_URL = "https://myserver.example.com:8443/api/v1";  // 非標準ポート例
#else
// ①② HTTP 接続: IP アドレスまたはホスト名:ポート を指定
const char* SERVER_URL = "http://192.168.1.100:8000/api/v1";
// const char* SERVER_URL = nullptr;  // nullptr にすると SENHUB_DEFAULT_URL を使用
#endif
// ====================

// ISRG Root X1 証明書（Let's Encrypt ルートCA）
// USE_TLS=true の場合のみ使用。senhub.example.com の証明書はこれで検証可能。
// 別CAを使う場合は対応するルートCA証明書に差し替えること。
#if USE_TLS
const char* root_ca = \
"-----BEGIN CERTIFICATE-----\n"
"MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw\n"
// ... (ISRG Root X1 全文を貼り付ける)
"-----END CERTIFICATE-----\n";

WiFiClientSecure client;
#else
WiFiClient client;
#endif

Senhub senhub;

// テスト状態
int  loopCount     = 0;
bool lastMachineOn = false;


void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n=== Senhub テスト開始 ===");

    // WiFi 接続
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    Serial.print("WiFi 接続中");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println();
    Serial.print("接続完了 IP: ");
    Serial.println(WiFi.localIP());

    // Senhub 初期化
    // USE_TLS=true の場合はルートCA証明書を設定
#if USE_TLS
    client.setCACert(root_ca);
#endif

    // SERVER_URL が nullptr なら SENHUB_DEFAULT_URL（または #define で上書きした URL）を使用
    senhub.begin(CHANNEL_ID, WRITE_KEY, &client, SERVER_URL);

    // バッチ設定（テスト用: 3件で送信・10秒タイムアウト）
    senhub.setBatchSize(3);
    senhub.setBatchTimeout(10000);

    Serial.printf("チャネル: %d  バッチサイズ: 3件 or 10秒\n\n", CHANNEL_ID);
}


void loop() {
    loopCount++;

    // -----------------------------------------------
    // センサーデータ送信テスト
    // -----------------------------------------------
    float temp  = 20.0f + (loopCount % 10) * 0.5f;  // 疑似温度データ
    float humid = 50.0f + (loopCount %  5) * 1.0f;  // 疑似湿度データ
    int   pulse = loopCount % 100;                   // 疑似カウンタ

    senhub.set(1, temp);    // d1: 温度
    senhub.set(2, humid);   // d2: 湿度
    senhub.set(3, pulse);   // d3: カウンタ

    bool queued = senhub.send();

    Serial.printf("[%3d] set d1=%.1f d2=%.1f d3=%d  send()=%s",
                  loopCount, temp, humid, pulse,
                  queued ? "queued" : "NG");

    int status = senhub.getLastStatus();
    if (status > 0) {
        Serial.printf("  HTTP=%d %s", status, status == 200 ? "OK" : "NG");
    }
    Serial.println();

    // -----------------------------------------------
    // ON/OFF イベント送信テスト（10ループごとにトグル）
    // -----------------------------------------------
    bool machineOn = ((loopCount / 10) % 2 == 0);

    if (machineOn != lastMachineOn) {
        senhub.setEvent(4, machineOn ? 1 : 0);   // d4: 機器状態
        bool evSent = senhub.sendEvent();

        Serial.printf("[%3d] ★ イベント d4=%d (%s)  sendEvent()=%s  HTTP=%d\n",
                      loopCount,
                      machineOn ? 1 : 0,
                      machineOn ? "ON" : "OFF",
                      evSent ? "OK" : "NG",
                      senhub.getLastStatus());

        lastMachineOn = machineOn;
    }

    delay(1000);  // 1秒間隔
}
