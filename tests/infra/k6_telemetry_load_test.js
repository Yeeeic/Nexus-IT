import http from 'k6/http';
import { check } from 'k6';
import crypto from 'k6/crypto';

// Configuration and performance budgets according to Roadmap Increment 14
export const options = {
  scenarios: {
    // 200 agents / 30 s = 6.67 batches/s. Arrival rate measures API throughput,
    // independent of virtual-user sleep and response time.
    steady_state_agents: {
      executor: 'constant-arrival-rate',
      rate: 7,
      timeUnit: '1s',
      duration: '2m',
      preAllocatedVUs: 20,
      maxVUs: 100,
    },
    // Explicit 20 batches/s burst after steady state.
    burst_load_spike: {
      executor: 'constant-arrival-rate',
      rate: 20,
      timeUnit: '1s',
      duration: '30s',
      startTime: '2m',
      preAllocatedVUs: 50,
      maxVUs: 200,
    },
  },
  thresholds: {
    // Performance budget: P99 latency must be under 150ms
    http_req_duration: ['p(95)<100', 'p(99)<150'],
    // Zero-tolerance for unhandled server errors (5xx)
    http_req_failed: ['rate<0.01'],
  },
};

const BASE_URL = __ENV.NEXUS_API_URL || 'http://127.0.0.1:8000';
const DEVICE_ID = __ENV.NEXUS_TEST_DEVICE_ID;
const AGENT_BEARER_TOKEN = __ENV.NEXUS_AGENT_TOKEN;

if (!DEVICE_ID || !AGENT_BEARER_TOKEN) {
  throw new Error('NEXUS_TEST_DEVICE_ID and NEXUS_AGENT_TOKEN are required');
}

// Helper to generate RFC4122 UUID v4
function uuidv4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export default function () {
  const batchId = uuidv4();
  const timestamp = new Date().toISOString();

  // Synthetic telemetry samples for typical agent payload
  const samples = [
    {
      metric_name: 'system.cpu.usage',
      metric_value: '42.5000',
      recorded_at: timestamp,
    },
    {
      metric_name: 'system.memory.used_percent',
      metric_value: '68.1200',
      recorded_at: timestamp,
    },
    {
      metric_name: 'system.disk.used_percent',
      metric_value: '54.3000',
      recorded_at: timestamp,
    },
    {
      metric_name: 'network.bytes_sent',
      metric_value: '1048576.0000',
      recorded_at: timestamp,
    },
  ];

  // Compute canonical SHA-256 digest
  const canonicalSamples = samples.map((sample) => ({
    labels: {},
    metric_name: sample.metric_name,
    metric_value: sample.metric_value,
    recorded_at: sample.recorded_at,
  }));
  const serialized = JSON.stringify(canonicalSamples);
  const payloadDigest = crypto.sha256(serialized, 'hex');

  const payload = JSON.stringify({
    batch_id: batchId,
    payload_digest: payloadDigest,
    samples: samples,
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${AGENT_BEARER_TOKEN}`,
      'User-Agent': 'nexus-agent-loadtest/1.0',
    },
    timeout: '5s',
  };

  const url = `${BASE_URL}/api/v1/devices/${DEVICE_ID}/metrics/batches`;
  const res = http.post(url, payload, params);

  // Authentication or validation failures invalidate the load result.
  check(res, {
    'status is 202 or idempotent 200': (r) => r.status === 202 || r.status === 200,
    'response duration < 150ms': (r) => r.timings.duration < 150,
  });
}
