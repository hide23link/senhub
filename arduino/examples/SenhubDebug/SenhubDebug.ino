#include <M5Atom.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>   // ← HTTPS用に変更
#include "Senhub.h"

// ===== 設定 =====
const char* WIFI_SSID  = "YOUR_SSID";
const char* WIFI_PASS  = "YOUR_PASSWORD";
const char* WRITE_KEY  = "test_writeKey";   // ← channels.yaml の write_key に合わせる
const char* SERVER_URL = "https://senhub.hide23.link/api/v1";  // ← https に戻す
const unsigned int CHANNEL_ID = 100;
// ================

WiFiClientSecure client;  // ← Secure に変更
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

    // HTTPS: 証明書検証をスキップ（テスト用）
    client.setInsecure();

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

    float temp  = 23.5f;
    float humid = 60.2f;

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
