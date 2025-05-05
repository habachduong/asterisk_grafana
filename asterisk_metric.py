from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime
import redis
import time
import configparser
import os
import logging
import traceback
from redis_OPS import *

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Đọc config
def read_config(config_path='/etc/OPS.conf'):
    if not os.path.exists(config_path):
        logger.error(f"Config file {config_path} does not exist")
        raise FileNotFoundError(f"Config file {config_path} does not exist")
    config = configparser.ConfigParser()
    config.read(config_path)
    return config

config = read_config()

REDIS_HOST = config.get('global', 'redis_host', fallback='localhost')
REDIS_PORT = config.getint('global', 'redis_port', fallback=6379)
REDIS_PASSWORD = config.get('global', 'redis_password', fallback=None)
REDIS_DB = config.getint('global', 'redis_db', fallback=0)

INFLUXDB_URL = config.get('global', 'influxdb_url', fallback='http://localhost:8086')
INFLUXDB_TOKEN = config.get('global', 'influxdb_token', fallback='my-token')
INFLUXDB_ORG = config.get('global', 'influxdb_org', fallback='TCB')
INFLUXDB_BUCKET = config.get('global', 'influxdb_bucket', fallback='redis_metrics')

index_campaign = "campaign_infor"
index_agent = "agents_infor"
index_lead = "leads_infor"

def connect_to_redis():
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        db=REDIS_DB,
        decode_responses=True
    )
    client.ping()
    return client

def connect_to_influxdb():
    return InfluxDBClient(
        url=INFLUXDB_URL,
        token=INFLUXDB_TOKEN,
        org=INFLUXDB_ORG
    )

def count_keys_by_pattern(redis_client, pattern):
    count = 0
    cursor = 0
    while True:
        cursor, keys = redis_client.scan(cursor=cursor, match=pattern, count=1000)
        count += len(keys)
        if cursor == 0:
            break
    return count

def collect_redis_metrics(redis_client):
    try:
        total_keys = redis_client.dbsize()
        miss_keys = count_keys_by_pattern(redis_client, "miss*")
        dialog_keys = count_keys_by_pattern(redis_client, "dialog*")

        campaign_started = get_total_campaign_by_status(conn, index_campaign, 1)
        total_agent_avaiable = get_total_agent_avaiable_ver1(conn, index_agent)
        total_MN_calls_count = get_total_MN_calls(conn)
        total_AT_calls_count = get_total_AT_calls(conn)
        lead_sums = get_lead_total_group_by_status(conn, index_lead)

        calls_info = {}
        if lead_sums is not None:
            for lead_sum in lead_sums:
                status = lead_sum[1].decode("UTF-8")
                if int(status) < 0:
                    status = 'a' + str(-int(status))
                calls_info[f'status_{status}'] = int(lead_sum[3])

        for key in ['status_0','status_1','status_2','status_3','status_4','status_5','status_6','status_a1','status_a2','status_a4','status_a5','status_a6']:
            calls_info.setdefault(key, 0)

        # Đọc các key kiểu api_response_code_* từ Redis
        api_response_metrics = {}
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor=cursor, match="api_response_code_*", count=1000)
            for key in keys:
                try:
                    value = int(redis_client.get(key) or 0)
                    field_name = key.replace("api_response_code_", "api_resp_")
                    api_response_metrics[field_name] = value
                except Exception as e:
                    logger.warning(f"Cannot read {key}: {e}")
            if cursor == 0:
                break

        metrics = {
            "campaign_started": campaign_started,
            "total_keys": total_keys,
            "miss_keys": miss_keys,
            "dialog_keys": dialog_keys,
            "MN_active_call": total_MN_calls_count,
            "AT_active_call": total_AT_calls_count,
            "total_agent_avaiable": total_agent_avaiable,
            "lead_added": calls_info['status_0'],
            "lead_poped": calls_info['status_1'],
            "lead_originaled": calls_info['status_2'],
            "lead_dialed": calls_info['status_3'],
            "lead_ring": calls_info['status_4'],
            "lead_looking_agent": calls_info['status_5'],
            "lead_connected": calls_info['status_6'],
            "lead_hangup": calls_info['status_a1'],
            "lead_failed": calls_info['status_a2'],
            "lead_ag_no_answer": calls_info['status_a4'],
            "lead_no_answer": calls_info['status_a5'],
            "lead_busy": calls_info['status_a6'],
        }

        metrics.update(api_response_metrics)
        logger.info(f"[+] Collected metrics: {metrics}")
        return metrics
    except Exception as e:
        logger.error(f"Error in collect_redis_metrics(): {traceback.format_exc()}")
        raise

def push_to_influxdb(influx_client, metrics):
    write_api = influx_client.write_api(write_options=SYNCHRONOUS)
    point = Point("redis_metrics") \
        .tag("host", REDIS_HOST) \
        .tag("port", str(REDIS_PORT)) \
        .time(datetime.utcnow(), WritePrecision.NS)
    for k, v in metrics.items():
        point.field(k, v)
    write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
    logger.info(f"[+] Pushed metrics to InfluxDB")

def run_collector(interval=60):
    redis_client = connect_to_redis()
    influx_client = connect_to_influxdb()
    while True:
        try:
            metrics = collect_redis_metrics(redis_client)
            push_to_influxdb(influx_client, metrics)
            time.sleep(interval)
        except Exception as e:
            logger.error(f"run_collector error: {e}")
            time.sleep(interval)

if __name__ == "__main__":
    run_collector()
