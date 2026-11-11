// k6 run -e BASE=https://staging.example -e EMAIL=... -e PASSWORD=... ops/loadtest/k6-smoke.js
// Targets from the spec: p95 < 500 ms for ordinary internal API calls. Run against STAGING with production-sized data.
import http from "k6/http";
import { check, sleep } from "k6";
export const options = {
  scenarios: { steady: { executor: "constant-arrival-rate", rate: 30, timeUnit: "1s", duration: "5m", preAllocatedVUs: 50 } },
  thresholds: { http_req_duration: ["p(95)<500"], http_req_failed: ["rate<0.01"] },
};
export function setup() {
  const r = http.post(`${__ENV.BASE}/auth/login`, JSON.stringify({ email: __ENV.EMAIL, password: __ENV.PASSWORD }), { headers: { "Content-Type": "application/json" } });
  return { token: r.json("token") };
}
export default function (d) {
  const h = { headers: { Authorization: `Bearer ${d.token}` } };
  const me = http.get(`${__ENV.BASE}/me`, h);
  check(me, { "me 200": (r) => r.status === 200 });
  const co = (me.json("companies") || [])[0];
  if (co) for (const p of ["jobs", "payables", "invoices", "reports/jobs"]) check(http.get(`${__ENV.BASE}/companies/${co.id}/${p}`, h), { [p]: (r) => r.status === 200 || r.status === 403 });
  sleep(1);
}
