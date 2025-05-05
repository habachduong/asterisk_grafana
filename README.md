# OPS_KAMAILIO SYSTEM DOCUMENTATION

## Introduction

This document describes the OPS_Kamailio system, including all metrics collected, necessary configuration, and InfluxDB queries to retrieve data. The system uses InfluxDB for metrics storage and Grafana for visualization.

## Types of Metrics

### 1. SIP Metrics

These metrics monitor the response time (RTT) of SIP connections with SIP trunks and user devices (if configured).

**Metrics**: `sip_rtt_metrics`

**Tags and Fields**:
- Tags:
  - `host`: Redis server being monitored
  - `source`: Metrics collection source (python_rtt_checker)
  - `target`: Name of trunk or user being checked
  - `protocol`: Protocol used (tcp/udp)
- Fields:
  - `rtt`: Response time (ms)

**How it works**:
- Send SIP OPTIONS to trunks and devices
- Measure response time for each request
- Collect via both TCP and UDP and take the best result

**InfluxDB Query**:
```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "sip_rtt_metrics")
  |> filter(fn: (r) => r._field == "rtt")
  |> group(columns: ["target"])
  |> mean()
```

### 2. Container Metrics

These metrics monitor the status of containers in the OPS_Kamailio system.

**Metrics**: `system_metrics`

**Fields**:
- `container_{name}`: Number of containers by name (e.g., container_kamailio, container_mysql, etc.)
- `container_kamailio`: Kamailio status (1=Running, 0=Stopped)
- `container_mysql`: MySQL status (1=Running, 0=Stopped)

**How it works**:
- Connect to Podman API via port 9889
- Get list of running containers
- Check TCP connections to main services

**InfluxDB Query**:
```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "system_metrics")
  |> filter(fn: (r) => r._field =~ /container_.*/)
```

### 3. HTTP Response Metrics

These metrics monitor HTTP response codes from APIs.

**Metrics**: `redis_metrics` (API responses)

**Fields**:
- `api_resp_{code}`: Number of HTTP responses by status code (e.g., api_resp_200, api_resp_404, etc.)

**How it works**:
- Scan Redis keys with format `api_response_code_*`
- Convert and store in InfluxDB

**InfluxDB Query**:
```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field =~ /api_resp_.*/)
```

### 4. Asterisk Metrics

These metrics monitor the operation of the Asterisk PBX system and calls.

**Metrics**: `redis_metrics` (Asterisk data)

**Tags and Fields**:
- Tags:
  - `host`: Redis server
  - `port`: Redis port
- Fields:
  - `campaign_started`: Number of active campaigns
  - `total_keys`: Total number of keys in Redis
  - `miss_keys`: Number of miss keys
  - `dialog_keys`: Number of dialog keys
  - `MN_active_call`: Number of active manual calls
  - `AT_active_call`: Number of active automatic calls
  - `total_agent_avaiable`: Total number of available agents
  - `lead_added`: Number of leads added (status 0)
  - `lead_poped`: Number of leads popped (status 1)
  - `lead_originaled`: Number of leads started calling (status 2)
  - `lead_dialed`: Number of leads dialed (status 3)
  - `lead_ring`: Number of leads ringing (status 4)
  - `lead_looking_agent`: Number of leads looking for agent (status 5)
  - `lead_connected`: Number of leads connected (status 6)
  - `lead_hangup`: Number of leads disconnected (status -1)
  - `lead_failed`: Number of failed leads (status -2)
  - `lead_ag_no_answer`: Number of leads with no agent answer (status -4)
  - `lead_no_answer`: Number of leads with no answer (status -5)
  - `lead_busy`: Number of busy leads (status -6)

**How it works**:
- Collect data from Redis by tables and indexes
- Count different types of keys
- Analyze lead status by status code
- Combine with metrics from HTTP responses

## InfluxDB Queries

This section provides useful InfluxDB queries for monitoring and analyzing metrics of the OPS_Kamailio system. The queries are written in Flux, the query language of InfluxDB 2.x.

### SIP Metrics Queries

#### Average Response Time for Each Trunk

```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "sip_rtt_metrics")
  |> filter(fn: (r) => r._field == "rtt")
  |> group(columns: ["target"])
  |> mean()
  |> yield(name: "mean_rtt_by_trunk")
```

#### Maximum and Minimum Response Time for Each Trunk

```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "sip_rtt_metrics")
  |> filter(fn: (r) => r._field == "rtt")
  |> group(columns: ["target"])
  |> reduce(
      identity: {max: 0.0, min: 9999.0},
      fn: (r, accumulator) => ({
          max: if r._value > accumulator.max then r._value else accumulator.max,
          min: if r._value < accumulator.min then r._value else accumulator.min
      })
  )
  |> yield(name: "min_max_rtt")
```

#### RTT Trend Monitoring Over Time

```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "sip_rtt_metrics")
  |> filter(fn: (r) => r._field == "rtt")
  |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
  |> yield(name: "rtt_trend")
```

#### RTT Distribution by Protocol (TCP vs UDP)

```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "sip_rtt_metrics")
  |> filter(fn: (r) => r._field == "rtt")
  |> group(columns: ["protocol", "target"])
  |> mean()
  |> yield(name: "protocol_rtt_comparison")
```

### Container Metrics Queries

#### Current Status of All Containers

```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "system_metrics")
  |> filter(fn: (r) => r._field =~ /container_.*/)
  |> last()
  |> yield(name: "container_status")
```

#### Monitor Inactive Containers Over Last 24 Hours

```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "system_metrics")
  |> filter(fn: (r) => r._field =~ /container_.*/)
  |> filter(fn: (r) => r._value == 0)
  |> group(columns: ["_field"])
  |> count()
  |> yield(name: "container_downtime_count")
```

#### Kamailio Uptime Statistics

```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "system_metrics")
  |> filter(fn: (r) => r._field == "container_kamailio")
  |> map(fn: (r) => ({ r with uptime: float(v: r._value) }))
  |> cumulativeSum(columns: ["uptime"])
  |> yield(name: "kamailio_uptime_stats")
```

### HTTP Response Metrics Queries

#### HTTP Code Statistics by Frequency

```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field =~ /api_resp_.*/)
  |> last()
  |> sort(columns: ["_value"], desc: true)
  |> yield(name: "http_response_frequency")
```

#### Monitor HTTP Errors (4xx, 5xx)

```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field =~ /api_resp_(4|5).*/)
  |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
  |> yield(name: "http_errors_per_hour")
```

#### HTTP Error Rate

```flux
error_count = from(bucket: "ASTERRISK-OPS")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field =~ /api_resp_(4|5).*/)
  |> sum()

total_count = from(bucket: "ASTERRISK-OPS")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field =~ /api_resp_.*/)
  |> sum()

join(
  tables: {error: error_count, total: total_count},
  on: ["_start", "_stop"]
)
  |> map(fn: (r) => ({
      _time: r._time,
      error_rate: float(v: r._value_error) / float(v: r._value_total) * 100.0
  }))
  |> yield(name: "http_error_rate")
```

### Asterisk Metrics Queries

#### Active Calls Query

```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field == "MN_active_call" or r._field == "AT_active_call")
  |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
  |> yield(name: "active_calls")
```

#### Lead Status Distribution

```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field =~ /lead_.*/)
  |> last()
  |> group(columns: ["_field"])
  |> yield(name: "lead_status_distribution")
```

#### Call Success Rate

```flux
// Successful calls are those that are connected (lead_connected)
success = from(bucket: "ASTERRISK-OPS")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field == "lead_connected")
  |> last()
  |> map(fn: (r) => ({r with _value: float(v: r._value)}))

// Total calls = sum of all lead statuses
total = from(bucket: "ASTERRISK-OPS")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field =~ /lead_(connected|hangup|failed|ag_no_answer|no_answer|busy)/)
  |> last()
  |> sum(column: "_value")

join(
  tables: {success: success, total: total},
  on: ["_start", "_stop"]
)
  |> map(fn: (r) => ({
      _time: r._time,
      success_rate: float(v: r._value_success) / float(v: r._value_total) * 100.0
  }))
  |> yield(name: "call_success_rate")
```

#### Available Agents Over Time

```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field == "total_agent_avaiable")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> yield(name: "agent_availability")
```

#### Number of Active Campaigns

```flux
from(bucket: "ASTERRISK-OPS")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field == "campaign_started")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> yield(name: "active_campaigns")
```

### Combined Queries

#### System Overview Dashboard

```flux
// Container status
container_status = from(bucket: "ASTERRISK-OPS")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "system_metrics")
  |> filter(fn: (r) => r._field =~ /container_.*/)
  |> last()

// Total active calls
active_calls = from(bucket: "ASTERRISK-OPS")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field == "MN_active_call" or r._field == "AT_active_call")
  |> sum(column: "_value")
  |> last()

// Number of available agents
available_agents = from(bucket: "ASTERRISK-OPS")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field == "total_agent_avaiable")
  |> last()

// Number of active campaigns
active_campaigns = from(bucket: "ASTERRISK-OPS")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field == "campaign_started")
  |> last()

union(
  tables: [container_status, active_calls, available_agents, active_campaigns]
)
  |> yield(name: "system_overview")
```

#### SIP Response Time and HTTP Error Rate

```flux
// SIP response time
sip_rtt = from(bucket: "ASTERRISK-OPS")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "sip_rtt_metrics")
  |> filter(fn: (r) => r._field == "rtt")
  |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)

// HTTP error rate
error_count = from(bucket: "ASTERRISK-OPS")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field =~ /api_resp_(4|5).*/)
  |> sum()

total_count = from(bucket: "ASTERRISK-OPS")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "redis_metrics")
  |> filter(fn: (r) => r._field =~ /api_resp_.*/)
  |> sum()

http_error_rate = join(
  tables: {error: error_count, total: total_count},
  on: ["_start", "_stop"]
)
  |> map(fn: (r) => ({
      _time: r._time,
      _field: "http_error_rate",
      _value: float(v: r._value_error) / float(v: r._value_total) * 100.0
  }))

union(
  tables: [sip_rtt, http_error_rate]
)
  |> yield(name: "performance_metrics")
```

## Display in Grafana

These metrics are designed to be easily integrated with Grafana. Here are some suggested dashboards:

1. **System Overview**
   - Container status
   - Total active calls
   - Total available agents
   - Number of running campaigns

2. **SIP Monitoring**
   - RTT response time by trunk
   - SIP connection success rate

3. **Call Analysis**
   - Lead status distribution
   - Call success/failure rate
   - Number of calls over time

4. **API Performance**
   - HTTP response code ratio
   - API response time

## Useful Query Variations

### Changing Query Time Range

Replace `range(start: -1h)` in queries to change time range:

- `range(start: -15m)`: Last 15 minutes
- `range(start: -1h)`: Last 1 hour
- `range(start: -24h)`: Last 24 hours
- `range(start: -7d)`: Last 7 days
- `range(start: -30d)`: Last 30 days
- `range(start: -1h, stop: now())`: Data from 1 hour ago to now
- `range(start: v.timeRangeStart, stop: v.timeRangeStop)`: Use Grafana variables

### Changing Aggregation Window

Modify `aggregateWindow(every: 5m, fn: mean, createEmpty: false)` to adjust aggregation:

- `aggregateWindow(every: 1m, fn: mean, createEmpty: false)`: Aggregate every minute
- `aggregateWindow(every: 1h, fn: mean, createEmpty: false)`: Aggregate every hour
- `aggregateWindow(every: 1d, fn: mean, createEmpty: false)`: Aggregate every day

### Different Aggregation Functions

Replace `fn: mean` in `aggregateWindow()` with other functions:

- `fn: mean`: Average value
- `fn: median`: Median value
- `fn: max`: Maximum value
- `fn: min`: Minimum value
- `fn: sum`: Sum of values
- `fn: count`: Count of values

## Common Troubleshooting

1. **Cannot connect to InfluxDB**
   - Check `influxdb_url` and `influxdb_token` parameters in OPS.conf
   - Verify InfluxDB is running and accessible from metrics server

2. **No SIP data visible**
   - Check if port 5061 is open
   - Verify SIP trunks are correctly configured in sip_metric.py file

3. **No container metrics visible**
   - Check if Podman socket is available at /run/podman/podman.sock
   - Verify socat is running and forwarding the correct port

4. **Data not appearing in InfluxDB**
   - Check metric container logs
   - Verify `influxdb_bucket` and `influxdb_org` configuration 
