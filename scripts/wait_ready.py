"""Wait for readiness, failing early on image/configuration/startup errors."""

import argparse
import json
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", default="kaspersky-vllm-cpu")
    parser.add_argument("--timeout", type=int, default=1800,
                        help="Overall startup deadline in seconds, including the first model download.")
    args = parser.parse_args()
    command = ["kubectl", "--context", args.context, "-n", "llm-inference"]
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        result = subprocess.run(command + ["get", "pods", "-l", "app=vllm", "-o", "json"], capture_output=True, text=True, check=True)
        pods = json.loads(result.stdout)["items"]
        for pod in pods:
            if pod["metadata"].get("deletionTimestamp"):
                continue
            conditions = pod.get("status", {}).get("conditions", [])
            if any(condition["type"] == "Ready" and condition["status"] == "True" for condition in conditions):
                print("The vLLM Pod is ready.")
                return
            statuses = pod.get("status", {}).get("containerStatuses", []) + pod.get("status", {}).get("initContainerStatuses", [])
            for status in statuses:
                waiting = status.get("state", {}).get("waiting", {})
                terminated = status.get("state", {}).get("terminated", {})
                failed = waiting.get("reason") in {"CrashLoopBackOff", "ImagePullBackOff", "ErrImageNeverPull", "CreateContainerConfigError", "CreateContainerError"}
                failed = failed or (terminated.get("exitCode", 0) != 0 and (status["name"] == "server" or status.get("restartCount", 0) >= 2))
                if failed:
                    # No client requests have been sent yet: these are startup diagnostics.
                    logs = subprocess.run(command + ["logs", pod["metadata"]["name"], "-c", status["name"], "--tail=30"], capture_output=True, text=True)
                    print(logs.stdout)
                    raise RuntimeError(f"Container {status['name']} failed before readiness: {waiting.get('reason') or terminated.get('reason')}.")
        time.sleep(3)
    raise TimeoutError("The vLLM Pod did not become ready.")


if __name__ == "__main__":
    main()
