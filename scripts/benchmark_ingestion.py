"""Ingestion throughput benchmark.

Runs against the in-process ASGI app (no network) to measure application-level
throughput and latency. Results are indicative of app overhead; full-system
throughput additionally depends on Postgres/Redis and deployment topology.

Usage:
    uv run python scripts/benchmark_ingestion.py --total 5000 --concurrency 64
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from uuid import uuid4

import httpx

from hr_agents.main import create_app


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(int(len(ordered) * fraction), len(ordered) - 1)
    return ordered[index]


async def run_benchmark(total: int, concurrency: int) -> dict[str, float]:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    job_id = str(uuid4())
    latencies: list[float] = []
    errors = 0

    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(transport=transport, base_url="http://bench") as client:

        async def submit(index: int) -> None:
            nonlocal errors
            payload = {
                "job_id": job_id,
                "source_channel": "api",
                "consent": {"granted": True, "policy_version": "1.0"},
                "candidate": {"full_name": f"Candidate {index}"},
            }
            headers = {"Idempotency-Key": f"bench-{index}"}
            async with semaphore:
                started = time.perf_counter()
                response = await client.post("/v1/applications", json=payload, headers=headers)
                latencies.append(time.perf_counter() - started)
            if response.status_code != 202:
                errors += 1

        started_at = time.perf_counter()
        await asyncio.gather(*(submit(index) for index in range(total)))
        elapsed = time.perf_counter() - started_at

    rps = total / elapsed
    return {
        "total": float(total),
        "concurrency": float(concurrency),
        "errors": float(errors),
        "elapsed_s": round(elapsed, 3),
        "throughput_rps": round(rps, 1),
        "throughput_rpm": round(rps * 60.0, 0),
        "p50_ms": round(percentile(latencies, 0.50) * 1000, 2),
        "p95_ms": round(percentile(latencies, 0.95) * 1000, 2),
        "p99_ms": round(percentile(latencies, 0.99) * 1000, 2),
        "mean_ms": round(statistics.mean(latencies) * 1000, 2),
        "audit_chain_ok": float(app.state.audit.verify() == -1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--total", type=int, default=5000)
    parser.add_argument("--concurrency", type=int, default=64)
    args = parser.parse_args()

    results = asyncio.run(run_benchmark(args.total, args.concurrency))
    width = max(len(key) for key in results)
    print("=" * (width + 18))
    print("HRAgents ingestion benchmark (in-process ASGI)")
    print("=" * (width + 18))
    for key, value in results.items():
        print(f"{key:<{width}} : {value}")


if __name__ == "__main__":
    main()
