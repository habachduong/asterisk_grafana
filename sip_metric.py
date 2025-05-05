import redis
import socket
import time
from datetime import datetime
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
import configparser
import os
import json
import re
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sip_rtt_monitor")

# Load config
def read_config(config_path='/etc/OPS.conf'):
    if not os.path.exists(config_path):
        logger.error(f"Config file {config_path} does not exist")
        raise FileNotFoundError(f"Config file {config_path} does not exist")
    config = configparser.ConfigParser()
    config.read(config_path)
    return config

config = read_config()

# Redis config
REDIS_HOST = config.get('global', 'redis_host', fallback='localhost')
REDIS_PORT = config.getint('global', 'redis_port', fallback=6379)
REDIS_PASSWORD = config.get('global', 'redis_password', fallback=None)
REDIS_DB = config.getint('global', 'redis_db', fallback=0)

# InfluxDB config
INFLUXDB_URL = config.get('global', 'influxdb_url', fallback='http://localhost:8086')
INFLUXDB_TOKEN = config.get('global', 'influxdb_token', fallback='my-token')
INFLUXDB_ORG = config.get('global', 'influxdb_org', fallback='TCB')
INFLUXDB_BUCKET = config.get('global', 'influxdb_bucket', fallback='ASTERRISK-OPS')

# Local IP & Flags
LOCAL_IP = config.get('global', 'local_ip', fallback='10.65.0.61')
CHECK_USERS = config.getboolean('global', 'check_users', fallback=False)

# Trunk list (static for now)
SIP_TRUNKS = [
    {"name": "trunk253", "ip": "10.65.0.253", "port": 5060},
    {"name": "trunk254", "ip": "10.65.0.254", "port": 5060},
    {"name": "trunk250", "ip": "10.65.0.250", "port": 5060},
]

def connect_to_redis():
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        db=REDIS_DB,
        decode_responses=True
    )

def connect_to_influxdb():
    return InfluxDBClient(
        url=INFLUXDB_URL,
        token=INFLUXDB_TOKEN,
        org=INFLUXDB_ORG
    )

def parse_contact_uri(uri):
    match = re.search(r'sip:.*?@([\d.]+):?(\d+)?', uri)
    if match:
        ip = match.group(1)
        port = int(match.group(2)) if match.group(2) else 5060
        return ip, port
    return None, None

def build_options(to_ip, to_port, call_id, protocol):
    return f"""OPTIONS sip:{to_ip}:{to_port} SIP/2.0
Via: SIP/2.0/{protocol.upper()} {LOCAL_IP}:5061;branch=z9hG4bK{call_id[:8]}
From: <sip:rtt-monitor@monitor.local>;tag={call_id[:4]}
To: <sip:{to_ip}:{to_port}>
Call-ID: {call_id}
CSeq: 1 OPTIONS
Contact: <sip:rtt-monitor@{LOCAL_IP}:5061>
Max-Forwards: 70
User-Agent: SIP RTT Monitor
Content-Length: 0

"""

def check_rtt(name, ip, port):
    best_rtt = -1
    best_proto = ""

    for protocol in ["TCP", "UDP"]:
        try:
            if protocol == "TCP":
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            sock.settimeout(2)
            call_id = f"{int(time.time()*1000)}@{LOCAL_IP}"
            msg = build_options(ip, port, call_id, protocol)

            start = time.time()
            if protocol == "TCP":
                sock.connect((ip, port))
                sock.sendall(msg.encode())
                data = sock.recv(2048)
            else:
                sock.sendto(msg.encode(), (ip, port))
                data, _ = sock.recvfrom(2048)

            rtt = (time.time() - start) * 1000
            if rtt > best_rtt:
                best_rtt = round(rtt, 2)
                best_proto = protocol.lower()
        except Exception as e:
            logger.warning(f"{name} - {protocol} timeout/error: {e}")
        finally:
            sock.close()

    return name, best_rtt, best_proto

def collect_rtt_metrics(redis_client):
    metrics = {}

    for trunk in SIP_TRUNKS:
        name, rtt, proto = check_rtt(trunk["name"], trunk["ip"], trunk["port"])
        if rtt is not None:
            metrics[name] = {"rtt": rtt, "protocol": proto}

    if CHECK_USERS:
        keys = redis_client.keys("ul:location:*")
        for key in keys:
            try:
                data_raw = redis_client.get(key)
                contacts = json.loads(data_raw)
                for contact_entry in contacts:
                    contact_uri = contact_entry.get("contact")
                    ip, port = parse_contact_uri(contact_uri)
                    if ip:
                        user_name = key.replace("ul:location:", "")
                        _, rtt, proto = check_rtt(user_name, ip, port)
                        if rtt is not None:
                            metrics[user_name] = {"rtt": rtt, "protocol": proto}
            except Exception as e:
                logger.warning(f"Error reading/parsing key {key}: {e}")

    return metrics

def push_to_influxdb(influx_client, metrics):
    write_api = influx_client.write_api(write_options=SYNCHRONOUS)
    now = datetime.utcnow()

    for target, data in metrics.items():
        try:
            rtt_value = float(data["rtt"])
            protocol = data["protocol"]

            point = Point("sip_rtt_metrics") \
                .tag("host", REDIS_HOST) \
                .tag("source", "python_rtt_checker") \
                .tag("target", target) \
                .tag("protocol", protocol) \
                .field("rtt", rtt_value) \
                .time(now, WritePrecision.NS)

            write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
            logger.info(f"[+] Wrote RTT ({protocol}) for {target}: {rtt_value} ms")

        except Exception as e:
            logger.warning(f"[!] Failed to write RTT for {target}: {e}")

def run(interval=60):
    redis_client = connect_to_redis()
    influx_client = connect_to_influxdb()
    while True:
        metrics = collect_rtt_metrics(redis_client)
        if metrics:
            push_to_influxdb(influx_client, metrics)
        time.sleep(interval)

if __name__ == "__main__":
    run(interval=60)