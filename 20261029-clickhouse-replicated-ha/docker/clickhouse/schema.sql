CREATE DATABASE IF NOT EXISTS lab ON CLUSTER lab;

CREATE TABLE IF NOT EXISTS lab.events ON CLUSTER lab
(
    ts      DateTime64(3),
    batch   UInt32,
    id      UInt64,
    user_id UInt32,
    value   Float64
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/lab/events', '{replica}')
PARTITION BY toYYYYMMDD(ts)
ORDER BY (user_id, ts);
