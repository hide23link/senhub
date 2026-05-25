/**
 * Senhub Arduino (ESP32) ライブラリ 実装
 */
#include "Senhub.h"

// ------------------------------------------------------------------
// コンストラクタ
// ------------------------------------------------------------------
Senhub::Senhub()
    : _channelId(0),
      _client(nullptr),
      _batchSize(SENHUB_BATCH_SIZE),
      _batchTimeout(SENHUB_BATCH_TIMEOUT),
      _lastStatus(0),
      _bufIdx(0),
      _lastSentAt(0),
      _eventField(0),
      _eventState(0),
      _eventReady(false)
{
    memset(_writeKey, 0, sizeof(_writeKey));
    memset(_buf,      0, sizeof(_buf));
    memset(_curD,     0, sizeof(_curD));
    memset(_curUsed,  0, sizeof(_curUsed));
}

// ------------------------------------------------------------------
// 初期化
// ------------------------------------------------------------------
void Senhub::begin(
    unsigned int channelId,
    const char*  writeKey,
    WiFiClient*  client,
    const char*  baseUrl
) {
    _channelId = channelId;
    strncpy(_writeKey, writeKey, sizeof(_writeKey) - 1);
    _writeKey[sizeof(_writeKey) - 1] = '\0';
    _client    = client;
    _baseUrl   = String(baseUrl);
    _bufIdx    = 0;
    _lastSentAt = millis();
}

// ------------------------------------------------------------------
// センサー値セット（int）
// ------------------------------------------------------------------
bool Senhub::set(int field, int value) {
    if (field < 1 || field > SENHUB_MAX_FIELDS) return false;
    snprintf(_curD[field - 1], sizeof(_curD[0]), "%d", value);
    _curUsed[field - 1] = true;
    return true;
}

// ------------------------------------------------------------------
// センサー値セット（float）
// ------------------------------------------------------------------
bool Senhub::set(int field, float value) {
    if (field < 1 || field > SENHUB_MAX_FIELDS) return false;
    dtostrf(value, 1, 4, _curD[field - 1]);
    _curUsed[field - 1] = true;
    return true;
}

// ------------------------------------------------------------------
// センサー値セット（文字列）
// ------------------------------------------------------------------
bool Senhub::set(int field, const char* value) {
    if (field < 1 || field > SENHUB_MAX_FIELDS) return false;
    strncpy(_curD[field - 1], value, sizeof(_curD[0]) - 1);
    _curD[field - 1][sizeof(_curD[0]) - 1] = '\0';
    _curUsed[field - 1] = true;
    return true;
}

// ------------------------------------------------------------------
// バッチ送信
// ------------------------------------------------------------------
bool Senhub::send() {
    // 現在の値をバッファにコピー
    if (_bufIdx < SENHUB_BATCH_SIZE) {
        _buf[_bufIdx].ts = millis() / 1000;
        for (int i = 0; i < SENHUB_MAX_FIELDS; i++) {
            strncpy(_buf[_bufIdx].d[i], _curD[i], sizeof(_curD[0]) - 1);
            _buf[_bufIdx].d[i][sizeof(_curD[0]) - 1] = '\0';
            _buf[_bufIdx].used[i] = _curUsed[i];
        }
        _bufIdx++;
    }

    // 現在値をリセット
    memset(_curD,    0, sizeof(_curD));
    memset(_curUsed, 0, sizeof(_curUsed));

    bool full    = (_bufIdx >= _batchSize);
    bool timeout = (millis() - _lastSentAt >= _batchTimeout);

    if (!full && !timeout) return true;  // 条件未達: バッファに留める

    return _flush();
}

// ------------------------------------------------------------------
// バッファを HTTP 送信する
// ------------------------------------------------------------------
bool Senhub::_flush() {
    if (_bufIdx == 0) return true;

    // CSV テキスト形式で組み立て
    String body = "writeKey=";
    body += _writeKey;
    body += "\n";

    for (int i = 0; i < _bufIdx; i++) {
        body += String(_buf[i].ts);
        for (int j = 0; j < SENHUB_MAX_FIELDS; j++) {
            body += ",";
            if (_buf[i].used[j]) {
                body += _buf[i].d[j];
            }
        }
        body += "\n";
    }

    bool ok = _httpPost("/dataarray", body);

    _bufIdx     = 0;
    _lastSentAt = millis();
    return ok;
}

// ------------------------------------------------------------------
// ON/OFF イベントセット
// ------------------------------------------------------------------
bool Senhub::setEvent(int field, int state) {
    if (field < 1 || field > SENHUB_MAX_FIELDS) return false;
    _eventField = field;
    _eventState = (state != 0) ? 1 : 0;
    _eventReady = true;
    return true;
}

// ------------------------------------------------------------------
// ON/OFF イベント即時送信
// ------------------------------------------------------------------
bool Senhub::sendEvent() {
    if (!_eventReady || !_client) return false;

    String body = "writeKey=";
    body += _writeKey;
    body += "\n";
    body += String(millis() / 1000);
    body += ",";
    body += String(_eventField);
    body += ",";
    body += String(_eventState);
    body += "\n";

    bool ok = _httpPost("/event", body);
    _eventReady = false;
    return ok;
}

// ------------------------------------------------------------------
// バッチサイズ変更
// ------------------------------------------------------------------
void Senhub::setBatchSize(int size) {
    if (size >= 1 && size <= SENHUB_BATCH_SIZE) {
        _batchSize = size;
    }
}

// ------------------------------------------------------------------
// タイムアウト変更
// ------------------------------------------------------------------
void Senhub::setBatchTimeout(unsigned long ms) {
    _batchTimeout = ms;
}

// ------------------------------------------------------------------
// 最後の HTTP ステータスコード取得
// ------------------------------------------------------------------
int Senhub::getLastStatus() {
    return _lastStatus;
}

// ------------------------------------------------------------------
// 内部: HTTP POST
// ------------------------------------------------------------------
bool Senhub::_httpPost(const String& endpoint, const String& body) {
    if (!_client) return false;

    String url = _channelUrl(endpoint);

    HTTPClient http;
    http.begin(*_client, url);
    http.addHeader("Content-Type", "text/plain");
    _lastStatus = http.POST(body);
    http.end();

    return (_lastStatus == 200);
}

// ------------------------------------------------------------------
// 内部: チャネルURL 生成
// ------------------------------------------------------------------
String Senhub::_channelUrl(const String& endpoint) {
    return _baseUrl + "/channels/" + String(_channelId) + endpoint;
}
