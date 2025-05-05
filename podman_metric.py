import requests
import socket
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

def read_config(config_path='/etc/OPS.conf'):
    if not os.path.exists(config_path):
        logger.error(f"File cấu hình {config_path} không tồn tại")
        raise FileNotFoundError(f"File cấu hình {config_path} không tồn tại")

    config = configparser.ConfigParser()
    config.read(config_path)
    return config

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

def get_container_counts():
    PODMAN_URL = "http://localhost:9889/v4.0.0/libpod/containers/json"
    try:
        response = requests.get(PODMAN_URL)
        if response.status_code != 200:
            logger.warning("Không thể lấy dữ liệu từ Podman API")
            return {}

        containers = response.json()
        running_containers = [c for c in containers if c["State"] == "running"]

        container_counts = {}
        for container in running_containers:
            name = container["Names"][0] if container["Names"] else "unknown"
            container_counts[name] = container_counts.get(name, 0) + 1

        return container_counts
    except Exception as e:
        logger.error(f"Lỗi khi lấy dữ liệu từ Podman: {e}")
        return {}

def check_tcp_connection(host, port, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return 1
    except Exception:
        return 0

def collect_metrics():
    metrics = {}

    # Lấy danh sách container đang chạy từ Podman
    container_counts = get_container_counts()
    metrics.update({f"container_{name}": count for name, count in container_counts.items()})

    # Bổ sung kiểm tra Kamailio và MySQL như container
    metrics["container_kamailio"] = check_tcp_connection("127.0.0.1", 8080)
    metrics["container_mysql"] = check_tcp_connection("127.0.0.1", 3306)

    logger.info(f"Đã thu thập metrics: {metrics}")
    return metrics

def push_to_influxdb(influx_client, metrics, config):
    try:
        write_api = influx_client.write_api(write_options=SYNCHRONOUS)
        point = Point("system_metrics").time(datetime.utcnow(), WritePrecision.NS)
        for key, value in metrics.items():
            point = point.field(key, value)

        write_api.write(
            bucket=config.get('global', 'influxdb_bucket', fallback='metrics'),
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

    try:
        while True:
            metrics = collect_metrics()
            push_to_influxdb(influx_client, metrics, config)
            logger.info(f"Đợi {interval} giây cho lần thu thập tiếp theo...")
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Collector bị dừng bởi người dùng")
    finally:
        influx_client.__del__()
        logger.info("Đã đóng kết nối")

if __name__ == "__main__":
    run_collector(interval=60)
