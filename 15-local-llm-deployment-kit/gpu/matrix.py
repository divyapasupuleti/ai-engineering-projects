"""Shared experiment-matrix logic: load configs, start a vLLM server, wait for it, benchmark it, stop it."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import vllm_bench

HERE = Path(__file__).resolve().parent


def load(path: Path = HERE / "configs.json") -> dict:
    return json.loads(path.read_text())


def select(cfg: dict, only: str) -> list[dict]:
    if not only:
        return cfg["configs"]
    wanted = {s.strip() for s in only.split(",") if s.strip()}
    chosen = [c for c in cfg["configs"] if c["label"] in wanted or c.get("group") in wanted]
    unknown = wanted - {c["label"] for c in chosen} - {c.get("group") for c in chosen}
    if unknown:
        raise SystemExit(f"unknown config or group: {', '.join(sorted(unknown))}")
    return chosen


def server_args(config: dict, server: dict) -> list[str]:
    return ["--model", config["model"], "--host", "0.0.0.0", "--port", str(server["port"]),
            *server["common_args"], *config["args"]]


def native_command(config: dict, server: dict) -> list[str]:
    return ["python3", "-m", "vllm.entrypoints.openai.api_server", *server_args(config, server)]


def docker_command(config: dict, server: dict, name: str, hf_cache: str, hf_token: str | None) -> list[str]:
    cmd = ["docker", "run", "--rm", "--name", name, "--gpus", "all", "--ipc=host",
           "-p", f"{server['port']}:{server['port']}", "-v", f"{hf_cache}:/root/.cache/huggingface"]
    if hf_token:
        cmd += ["-e", f"HF_TOKEN={hf_token}"]
    return cmd + [server["docker_image"], *server_args(config, server)]


def wait_ready(port: int, proc: subprocess.Popen, timeout_s: float, log_path: Path) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            tail = log_path.read_text(errors="ignore")[-3000:] if log_path.exists() else ""
            raise RuntimeError(f"vLLM exited with code {proc.returncode} before becoming ready:\n{tail}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(5)
    raise RuntimeError(f"vLLM not ready after {timeout_s:.0f} s; see {log_path}")


def server_version(port: int) -> str | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/version", timeout=3) as r:
            return json.loads(r.read()).get("version")
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
        return None


def run_one(config: dict, cfg: dict, command: list[str], out_path: Path, price: float | None,
            log_dir: Path, stop: callable | None = None) -> dict:
    """Start the server with `command`, benchmark it with the config's bench_args, always stop it."""
    server = cfg["server"]
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{config['label']}.server.log"
    with log_path.open("w") as log:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    try:
        t0 = time.time()
        wait_ready(server["port"], proc, server["ready_timeout_s"], log_path)
        load_s = round(time.time() - t0, 1)
        argv = ["--base-url", f"http://127.0.0.1:{server['port']}/v1", "--label", config["label"],
                "--out", str(out_path), *config.get("bench_args", [])]
        if price:
            argv += ["--gpu-price-per-hour", str(price)]
        return vllm_bench.run(vllm_bench.parse_args(argv), extra={
            "config": config, "server_command": command, "server_ready_s": load_s,
            "vllm_version": server_version(server["port"]), "slo": cfg["slo"]})
    finally:
        if stop:
            stop()
        proc.terminate()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
