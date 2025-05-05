import redis
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
import time
import logging
from datetime import datetime
import configparser
import os
import traceback

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Đọc file cấu hình
def read_config(config_path='/etc/OPS.conf'):
    if not os.path.exists(config_path):
        logger.error(f"File cấu hình {config_path} không tồn tại")
        raise FileNotFoundError(f"File cấu hình {config_path} không tồn tại")

    config = configparser.ConfigParser()
    config.read(config_path)
    return config

def connect_to_redis(config):
    try:
        client = redis.Redis(
            host=config.get('global', 'redis_host', fallback='localhost'),
            port=config.getint('global', 'redis_port', fallback=6379),
            password=config.get('global', 'redis_password', fallback=None),
            db=config.getint('global', 'redis_db', fallback=0),
            decode_responses=True
        )
        client.ping()
        logger.info("Kết nối Redis thành công")
        return client
    except Exception as e:
        logger.error(f"Không thể kết nối Redis: {e}")
        raise

def connect_to_influxdb(config):
    try:
        influx_client = InfluxDBClient(
            url=config.get('global', 'influxdb_url', fallback='http://localhost:8086'),
            token=config.get('global', 'influxdb_token', fallback='my-token'),
            org=config.get('global', 'influxdb_org', fallback='TCB')
        )
        logger.info("Kết nối InfluxDB thành công")
        return influx_client
    except Exception as e:
        logger.error(f"Không thể kết nối đến InfluxDB: {e}")
        raise

def collect_metrics(redis_client):
    metrics = {}
    try:
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor=cursor, match="api_response_code_*", count=1000)
            for key in keys:
                try:
                    value = int(redis_client.get(key) or 0)
                    field_name = key.replace("api_response_code_", "api_resp_")
                    metrics[field_name] = value
                except Exception as e:
                    logger.warning(f"Lỗi khi đọc key {key} từ Redis: {e}")
            if cursor == 0:
                break
    except Exception as e:
        logger.error(f"Lỗi trong collect_metrics(): {traceback.format_exc()}")
    logger.info(f"Đã thu thập metrics từ Redis: {metrics}")
    return metrics

def push_to_influxdb(influx_client, metrics, config):
    try:
        write_api = influx_client.write_api(write_options=SYNCHRONOUS)
        point = Point("redis_metrics").time(datetime.utcnow(), WritePrecision.NS)
        for key, value in metrics.items():
            point = point.field(key, value)
        write_api.write(
            bucket=config.get('global', 'influxdb_bucket', fallback='redis_metrics'),
            org=config.get('global', 'influxdb_org', fallback='TCB'),
            record=point
        )
        logger.info("Đã đẩy metrics vào InfluxDB thành công")
    except Exception as e:
        logger.error(f"Lỗi khi đẩy metrics vào InfluxDB: {e}")
        raise

def run_collector(interval=60):
    config = read_config()
    influx_client = connect_to_influxdb(config)
    redis_client = connect_to_redis(config)

    try:
        while True:
            metrics = collect_metrics(redis_client)
            if metrics:
                push_to_influxdb(influx_client, metrics, config)
            logger.info(f"Đợi {interval} giây cho lần thu thập tiếp theo...")
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Collector bị dừng bởi người dùng")
    finally:
        influx_client.__del__()
        logger.info("Đã đóng kết nối InfluxDB")

if __name__ == "__main__":
    run_collector(interval=60)
