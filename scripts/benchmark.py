"""Streaming CPU inference benchmark with warm-up and unique prompt prefixes."""

import argparse
import concurrent.futures
import datetime
import json
import math
import statistics
import time
from pathlib import Path
from urllib.request import Request, urlopen


def measure(base_url, token, model, prompt, max_tokens):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True, "stream_options": {"include_usage": True},
        "max_tokens": max_tokens, "temperature": 0,
    }).encode()
    query = Request(base_url.rstrip("/") + "/v1/chat/completions", data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + token,
    })
    started = time.perf_counter()
    ttft = None
    usage = None
    with urlopen(query, timeout=300) as response:
        for raw_line in response:
            line = raw_line.decode().strip()
            if not line.startswith("data: "):
                continue
            if line == "data: [DONE]":
                break
            chunk = json.loads(line[6:])
            if "error" in chunk:
                raise RuntimeError("The streaming endpoint returned an error.")
            if chunk.get("usage"):
                usage = chunk["usage"]
            if ttft is None and any(choice.get("delta", {}).get("content") for choice in chunk.get("choices", [])):
                ttft = time.perf_counter() - started
    latency = time.perf_counter() - started
    if ttft is None or usage is None or not usage.get("completion_tokens"):
        raise RuntimeError("The response is missing content or token-usage metrics.")
    return {"ttft_s": ttft, "latency_s": latency, **{key: usage[key] for key in ("prompt_tokens", "completion_tokens")}}


def percentile95(values):
    return sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token-file", type=Path, default=Path(".local/api-token"))
    parser.add_argument("--model", default="local-instruct")
    parser.add_argument("--requests", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--output", type=Path, default=Path("results/benchmark.json"))
    args = parser.parse_args()
    if min(args.requests, args.concurrency, args.max_tokens) < 1:
        parser.error("Request count, concurrency and max tokens must be positive.")
    token = args.token_file.read_text().strip()
    long_context = "A container packages an application with its dependencies and runs isolated processes. " * 64
    cases = {"short": "Explain containers in one sentence.", "long": long_context + "Summarize the text in one sentence."}
    report = {
        "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": args.model, "requests_per_case": args.requests,
        "concurrency": args.concurrency, "max_output_tokens": args.max_tokens,
        "warmup_requests_per_case": 1, "cases": {},
    }
    for name, prompt in cases.items():
        measure(args.base_url, token, args.model, "Warmup run. " + prompt, args.max_tokens)
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = [executor.submit(measure, args.base_url, token, args.model, f"Request {index:06d}. " + prompt, args.max_tokens) for index in range(args.requests)]
            measurements = [future.result() for future in futures]
        elapsed = time.perf_counter() - started
        ttfts = [item["ttft_s"] for item in measurements]
        latencies = [item["latency_s"] for item in measurements]
        report["cases"][name] = {
            "mean_input_tokens": statistics.mean(item["prompt_tokens"] for item in measurements),
            "total_output_tokens": sum(item["completion_tokens"] for item in measurements),
            "ttft_p50_s": statistics.median(ttfts), "ttft_p95_s": percentile95(ttfts),
            "latency_p50_s": statistics.median(latencies), "latency_p95_s": percentile95(latencies),
            "requests_per_second": len(measurements) / elapsed,
            "output_tokens_per_second": sum(item["completion_tokens"] for item in measurements) / elapsed,
            "wall_time_s": elapsed, "measurements": measurements,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("| Prompt | Input tokens | TTFT p50, s | TTFT p95, s | Latency p50, s | Output tokens/s | Requests/s |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for name, result in report["cases"].items():
        print(f"| {name} | {result['mean_input_tokens']:.0f} | {result['ttft_p50_s']:.3f} | {result['ttft_p95_s']:.3f} | {result['latency_p50_s']:.3f} | {result['output_tokens_per_second']:.2f} | {result['requests_per_second']:.2f} |")


if __name__ == "__main__":
    main()
