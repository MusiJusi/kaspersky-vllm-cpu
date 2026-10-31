"""Exercise authentication, generation, streaming, and server-log privacy."""

import argparse
import json
import subprocess
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(base_url, path, token=None, payload=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(payload).encode() if payload is not None else None
    query = Request(base_url.rstrip("/") + path, data=data, headers=headers)
    try:
        with urlopen(query, timeout=180) as response:
            return response.status, response.read(), response.headers
    except HTTPError as error:
        return error.code, error.read(), error.headers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token-file", type=Path, default=Path(".local/api-token"))
    parser.add_argument("--context", default="kaspersky-vllm-cpu")
    parser.add_argument("--skip-log-check", action="store_true")
    args = parser.parse_args()
    token = args.token_file.read_text().strip()
    marker = "PRIVATE_INPUT_" + uuid.uuid4().hex
    output_marker = "PRIVATE_OUTPUT_" + uuid.uuid4().hex
    private_values = [token, marker, output_marker]

    for credential in (None, "invalid-token"):
        status, _, _ = request(args.base_url, "/v1/models", credential)
        if status != 401:
            raise RuntimeError(f"Expected 401 without a valid token, received {status}.")

    status, raw, _ = request(args.base_url, "/v1/models", token)
    if status != 200:
        raise RuntimeError(f"Model listing failed with HTTP {status}.")
    model = json.loads(raw)["data"][0]["id"]
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": f"{marker}\nReply with exactly this string: {output_marker}"}],
        "max_tokens": 64,
        "temperature": 0,
    }
    status, raw, headers = request(args.base_url, "/v1/chat/completions", token, payload)
    if status != 200:
        raise RuntimeError(f"Generation failed with HTTP {status}.")
    content = json.loads(raw)["choices"][0]["message"]["content"]
    if not content or not headers.get("x-request-id"):
        raise RuntimeError("Generation returned no content or no audit request ID.")
    if len(content) >= 12:
        private_values.append(content)

    status, raw, _ = request(args.base_url, "/v1/chat/completions", token, {**payload, "stream": True})
    if status != 200 or b"data: [DONE]" not in raw:
        raise RuntimeError("Streaming generation failed.")
    streamed = []
    for line in raw.decode().splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            for choice in json.loads(line[6:]).get("choices", []):
                streamed.append(choice.get("delta", {}).get("content") or "")
    if len("".join(streamed)) >= 12:
        private_values.append("".join(streamed))

    status, _, _ = request(args.base_url, "/v1/chat/completions", token, {**payload, "max_tokens": marker})
    if status not in (400, 422):
        raise RuntimeError(f"Validation check returned unexpected HTTP {status}.")
    status, _, _ = request(args.base_url, "/" + marker + "?private=" + marker, token)
    if status != 404:
        raise RuntimeError(f"Unknown-path check returned unexpected HTTP {status}.")

    if not args.skip_log_check:
        result = subprocess.run(
            ["kubectl", "--context", args.context, "-n", "llm-inference", "logs", "deployment/vllm", "-c", "server"],
            capture_output=True, text=True, check=True,
        )
        logs = result.stdout + result.stderr
        if any(value in logs for value in private_values):
            raise RuntimeError("A private input, model output, or API token appeared in server logs.")
        events = []
        for line in logs.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not any(event.get("event") == "http_request" and event.get("route") == "/v1/chat/completions" and event.get("status") == 200 for event in events):
            raise RuntimeError("No successful generation request was found in audit logs.")

    print(json.dumps({
        "authentication": "passed", "generation": "passed", "streaming": "passed",
        "validation_error": "passed", "private_path": "passed",
        "log_privacy": "skipped" if args.skip_log_check else "passed",
        "response_characters": len(content),
    }, indent=2))


if __name__ == "__main__":
    main()
