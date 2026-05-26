#include <M5Atom.h>
#include <WiFi.h>
#include <WiFiClient.h>        // ← HTTP用（ローカルサーバー）
#include <time.h>              // ← NTP時刻同期用
#include <math.h>              // ← sinf() 変動値計算用
#include "Senhub.h"

// ===== 設定 =====
const char* WIFI_SSID  = "YOUR_SSID";
const char* WIFI_PASS  = "YOUR_PASSWORD";
const char* WRITE_KEY  = "test_writeKey";   // ← channels.yaml の write_key に合わせる
const char* SERVER_URL = "http://192.168.11.85:8000/api/v1";  // ← ローカルサーバー
const unsigned int CHANNEL_ID = 100;
// ================

WiFiClient client;             // ← HTTP用（Secureなし）
Senhub senhub;
int loopCount = 0;

void setup() {
    M5.begin(true, false, true);  // Serial有効, I2C無効, LED有効
    delay(500);

    Serial.println("\n=============================");
    Serial.println(" Senhub デバッグモード起動");
    Serial.println("=============================");
    Serial.printf("SSID      : %s\n", WIFI_SSID);
    Serial.printf("SERVER    : %s\n", SERVER_URL);
    Serial.printf("CHANNEL   : %d\n", CHANNEL_ID);
    Serial.printf("WRITE_KEY : %s\n", WRITE_KEY);
    Serial.println("-----------------------------");

    // WiFi接続
    Serial.print("WiFi 接続中");
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    int retry = 0;
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
        if (++retry > 40) {
            Serial.println("\n[ERROR] WiFi 接続タイムアウト（20秒）");
            Serial.printf("  ステータス: %d\n", WiFi.status());
            Serial.println("  → SSID/パスワードを確認してください");
            while (true) delay(1000);
        }
    }
    Serial.println(" 完了");
    Serial.printf("  IP アドレス : %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("  RSSI        : %d dBm\n", WiFi.RSSI());
    Serial.println("-----------------------------");

    // NTP時刻同期（JST = UTC+9）
    Serial.print("NTP 同期中");
    configTime(9 * 3600, 0, "pool.ntp.org", "ntp.jst.mfeed.ad.jp");
    struct tm timeinfo;
    int ntpRetry = 0;
    while (!getLocalTime(&timeinfo)) {
        delay(500);
        Serial.print(".");
        if (++ntpRetry > 20) {
            Serial.println("\n[WARNING] NTP 同期タイムアウト（タイムスタンプが不正確になります）");
            break;
        }
    }
    if (ntpRetry <= 20) {
        char timebuf[32];
        strftime(timebuf, sizeof(timebuf), "%Y-%m-%d %H:%M:%S", &timeinfo);
        Serial.printf(" 完了\n  現在時刻 : %s JST\n", timebuf);
    }
    Serial.println("-----------------------------");

    // Senhub 初期化
    senhub.begin(CHANNEL_ID, WRITE_KEY, &client, SERVER_URL);
    senhub.setBatchSize(1);       // デバッグ用: 1件ごとに即送信
    senhub.setBatchTimeout(3000); // 3秒でも送信

    Serial.println("Senhub 初期化完了（バッチサイズ=1 即時送信モード）");
    Serial.println("=============================\n");
    M5.dis.drawpix(0, 0x00ff00);  // 緑: 準備完了
}

void loop() {
    M5.update();
    loopCount++;

    // 疑似センサー値：ループカウントで±2℃ / ±5% 変動
    float temp  = 23.5f + 2.0f * sinf(loopCount * 0.3f);
    float humid = 60.0f + 5.0f * sinf(loopCount * 0.17f);

    Serial.printf("[%3d] set d1=%.1f d2=%.1f  → send()...", loopCount, temp, humid);

    senhub.set(1, temp);
    senhub.set(2, humid);
    bool result = senhub.send();
    int  status = senhub.getLastStatus();

    if (status == 200) {
        Serial.printf(" HTTP %d OK ✓\n", status);
        M5.dis.drawpix(0, 0x00ff00);  // 緑: 成功
    } else if (status > 0) {
        Serial.printf(" HTTP %d NG ✗\n", status);
        Serial.println("  → writeKey が間違っている可能性があります");
        M5.dis.drawpix(0, 0xff0000);  // 赤: 認証エラーなど
    } else if (result) {
        Serial.println(" バッファ積み込み（未送信）");
    } else {
        Serial.println(" 送信失敗（接続エラー）");
        Serial.printf("  WiFi状態: %d  RSSI: %d dBm\n",
                      WiFi.status(), WiFi.RSSI());
        M5.dis.drawpix(0, 0xff0000);  // 赤: 接続エラー
    }

    delay(1000);
}
