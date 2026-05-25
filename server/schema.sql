-- ============================================================
-- Senhub TimescaleDB スキーマ
-- 実行方法:
--   psql -d senhub -U senhub -f schema.sql
-- ============================================================

-- ============================================================
-- channels: チャンネル認証キー管理
-- ============================================================
CREATE TABLE IF NOT EXISTS channels (
    channel_id   INTEGER      PRIMARY KEY,
    write_key    VARCHAR(128) NOT NULL,
    read_key     VARCHAR(128) NOT NULL,
    name         VARCHAR(128) NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ============================================================
-- channel_properties: フィールドごとのメタ情報（name/unit/type）
-- ============================================================
CREATE TABLE IF NOT EXISTS channel_properties (
    channel_id  INTEGER      NOT NULL REFERENCES channels(channel_id) ON DELETE CASCADE,
    field       VARCHAR(4)   NOT NULL,   -- "d1"〜"d8"
    name        VARCHAR(64)  NOT NULL DEFAULT '',
    unit        VARCHAR(32)  NOT NULL DEFAULT '',
    type        VARCHAR(16)  NOT NULL DEFAULT 'sensor',  -- "sensor" or "event"
    PRIMARY KEY (channel_id, field)
);

-- ============================================================
-- sensor_data: 連続センサーデータ（Hypertable）
-- ※ Hypertable には外部キー制約を付与できないため、アプリ側で担保する
-- ============================================================
CREATE TABLE IF NOT EXISTS sensor_data (
    time        TIMESTAMPTZ      NOT NULL,
    channel_id  INTEGER          NOT NULL,
    d1  DOUBLE PRECISION,
    d2  DOUBLE PRECISION,
    d3  DOUBLE PRECISION,
    d4  DOUBLE PRECISION,
    d5  DOUBLE PRECISION,
    d6  DOUBLE PRECISION,
    d7  DOUBLE PRECISION,
    d8  DOUBLE PRECISION
);
SELECT create_hypertable('sensor_data', by_range('time'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_sensor_data_channel_time
    ON sensor_data (channel_id, time DESC);

-- ============================================================
-- events: ON/OFFイベントログ（Hypertable）
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    time        TIMESTAMPTZ  NOT NULL,
    channel_id  INTEGER      NOT NULL,
    field       SMALLINT     NOT NULL,   -- 1〜8 (d1〜d8)
    state       SMALLINT     NOT NULL,   -- 0=OFF / 1=ON
    duration    INTEGER                  -- OFF時に直前ON継続秒数を記録（秒）
);
SELECT create_hypertable('events', by_range('time'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_events_channel_time
    ON events (channel_id, time DESC);

-- ============================================================
-- 自動集約ビュー: 1分平均（Continuous Aggregate）
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS sensor_data_1min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time) AS bucket,
    channel_id,
    avg(d1) AS d1, avg(d2) AS d2, avg(d3) AS d3, avg(d4) AS d4,
    avg(d5) AS d5, avg(d6) AS d6, avg(d7) AS d7, avg(d8) AS d8
FROM sensor_data
GROUP BY bucket, channel_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('sensor_data_1min',
    start_offset => INTERVAL '1 hour',
    end_offset   => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE);

-- ============================================================
-- 自動集約ビュー: 1時間平均（Continuous Aggregate）
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS sensor_data_1hour
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    channel_id,
    avg(d1) AS d1, avg(d2) AS d2, avg(d3) AS d3, avg(d4) AS d4,
    avg(d5) AS d5, avg(d6) AS d6, avg(d7) AS d7, avg(d8) AS d8
FROM sensor_data
GROUP BY bucket, channel_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('sensor_data_1hour',
    start_offset => INTERVAL '1 day',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);
