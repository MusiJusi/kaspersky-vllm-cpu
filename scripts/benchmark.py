"""Streaming CPU inference benchmark with warm-up and unique prompt prefixes."""

import argparse
import concurrent.futures
import datetime
import json
import math
import statistics
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def measure(base_url, token, model, prompt, max_tokens, ignore_eos=False):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True, "stream_options": {"include_usage": True},
        "max_tokens": max_tokens, "temperature": 0,
    }
    if ignore_eos:
        payload["ignore_eos"] = True
    body = json.dumps(payload).encode()
    query = Request(base_url.rstrip("/") + "/v1/chat/completions", data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + token,
    })
    started = time.perf_counter()
    ttft = None
    usage = None
    completed = False
    with urlopen(query, timeout=300) as response:
        for raw_line in response:
            line = raw_line.decode().strip()
            if not line.startswith("data: "):
                continue
            if line == "data: [DONE]":
                completed = True
                break
            chunk = json.loads(line[6:])
            if "error" in chunk:
                raise RuntimeError("The streaming endpoint returned an error.")
            if chunk.get("usage"):
                usage = chunk["usage"]
            if ttft is None and any(choice.get("delta", {}).get("content") for choice in chunk.get("choices", [])):
                ttft = time.perf_counter() - started
    latency = time.perf_counter() - started
    if not completed or ttft is None or usage is None or not usage.get("completion_tokens"):
        raise RuntimeError("The response is incomplete or missing content/token-usage metrics.")
    if ignore_eos and usage["completion_tokens"] != max_tokens:
        raise RuntimeError("The response did not reach the requested fixed output length.")
    return {"ttft_s": ttft, "latency_s": latency, **{key: usage[key] for key in ("prompt_tokens", "completion_tokens")}}


def percentile95(values):
    return sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)]


def benchmark_case(args, token, prompt, prefix, concurrency):
    recorded_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for index in range(args.warmup_requests):
        measure(args.base_url, token, args.model, f"{prefix} Warmup {index:06d}. {prompt}", args.max_tokens, args.ignore_eos)
    measurements = []
    errors = []
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(
                measure, args.base_url, token, args.model,
                f"{prefix} Request {index:06d}. {prompt}", args.max_tokens, args.ignore_eos,
            ): index for index in range(args.requests)
        }
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                measurements.append({"request_index": index, **future.result()})
            except Exception as error:
                # Exception messages and HTTP error bodies may contain private data.
                failure = {"request_index": index, "error_type": type(error).__name__}
                if isinstance(error, HTTPError):
                    failure["http_status"] = error.code
                    error.close()
                errors.append(failure)
    elapsed = time.perf_counter() - started
    measurements.sort(key=lambda item: item["request_index"])
    errors.sort(key=lambda item: item["request_index"])
    result = {
        "recorded_at_utc": recorded_at,
        "successful_requests": len(measurements), "failed_requests": len(errors),
        "error_rate": len(errors) / args.requests, "errors": errors,
        "wall_time_s": elapsed, "measurements": measurements,
    }
    if measurements:
        ttfts = [item["ttft_s"] for item in measurements]
        latencies = [item["latency_s"] for item in measurements]
        inputs = [item["prompt_tokens"] for item in measurements]
        outputs = [item["completion_tokens"] for item in measurements]
        result.update({
            "mean_input_tokens": statistics.mean(inputs),
            "min_input_tokens": min(inputs), "max_input_tokens": max(inputs),
            "mean_output_tokens": statistics.mean(outputs),
            "min_output_tokens": min(outputs), "max_output_tokens": max(outputs),
            "total_output_tokens": sum(outputs),
            "ttft_p50_s": statistics.median(ttfts), "ttft_p95_s": percentile95(ttfts),
            "latency_p50_s": statistics.median(latencies), "latency_p95_s": percentile95(latencies),
            "requests_per_second": len(measurements) / elapsed,
            "output_tokens_per_second": sum(outputs) / elapsed,
        })
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token-file", type=Path, default=Path(".local/api-token"))
    parser.add_argument("--model", default="local-instruct")
    parser.add_argument("--requests", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--concurrency-levels", type=int, nargs="+", help="Run a suite at each concurrency level.")
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--warmup-requests", type=int, default=1)
    parser.add_argument("--ignore-eos", action="store_true", help="Generate exactly max-tokens for a controlled comparison.")
    parser.add_argument("--output", type=Path, default=Path("results/benchmark.json"))
    args = parser.parse_args(argv)
    levels = args.concurrency_levels if args.concurrency_levels is not None else [args.concurrency]
    if min(args.requests, args.max_tokens, *levels) < 1 or args.warmup_requests < 0:
        parser.error("Request count, concurrency and max tokens must be positive; warm-up must be non-negative.")
    if len(set(levels)) != len(levels):
        parser.error("Concurrency levels must be unique.")
    token = args.token_file.read_text().strip()
    long_context = "A container packages an application with its dependencies and runs isolated processes. " * 64
    cases = {"short": "Explain containers in one sentence.", "long": long_context + "Summarize the text in one sentence."}
    report = {
        "schema_version": 2, "status": "running", "run_id": uuid.uuid4().hex,
        "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": args.model, "requests_per_case": args.requests,
        "max_output_tokens": args.max_tokens, "ignore_eos": args.ignore_eos,
        "warmup_requests_per_case": args.warmup_requests,
        "load_model": "closed_loop; at most concurrency in-flight requests; no imposed arrival rate",
        "timing": "client HTTP request start to first non-empty content / SSE DONE; excludes executor queue wait",
        "percentile_method": "nearest_rank",
        "prompt_prefix": "unique run/series/request identifiers before the shared context",
        "case_order": list(cases),
    }
    if args.concurrency_levels is None:
        report.update({"concurrency": args.concurrency, "cases": {}})
        runs = [report]
    else:
        runs = [{"concurrency": level, "cases": {}} for level in levels]
        report.update({"concurrency_levels": levels, "runs": runs})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    print("| Prompt | Concurrency | Success/errors | Input tokens | TTFT p50, s | TTFT p95, s | Latency p50, s | Latency p95, s | Output tokens/s | Requests/s |", flush=True)
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |", flush=True)
    for run_index, run in enumerate(runs):
        for case_index, (name, prompt) in enumerate(cases.items()):
            prefix = f"Benchmark {report['run_id']}. Series {run_index:02d}{case_index:02d}."
            result = benchmark_case(args, token, prompt, prefix, run["concurrency"])
            run["cases"][name] = result
            # Persist completed cases even if a later case is interrupted.
            args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            if result["successful_requests"]:
                print(f"| {name} | {run['concurrency']} | {result['successful_requests']}/{result['failed_requests']} | {result['mean_input_tokens']:.1f} | {result['ttft_p50_s']:.3f} | {result['ttft_p95_s']:.3f} | {result['latency_p50_s']:.3f} | {result['latency_p95_s']:.3f} | {result['output_tokens_per_second']:.2f} | {result['requests_per_second']:.2f} |", flush=True)
            else:
                print(f"| {name} | {run['concurrency']} | 0/{result['failed_requests']} | - | - | - | - | - | - | - |", flush=True)
    report["completed_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report["status"] = "failed" if any(case["failed_requests"] for run in runs for case in run["cases"].values()) else "passed"
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
