#!/usr/bin/env python3
"""Sequentially launch fresh local Cursor agents for CA data-repair work.

Each iteration uses a new Agent (clear context) with the fixed prompt in
prompts/ca_data_repair_next.txt. Requires CURSOR_API_KEY.

Usage:
  export CURSOR_API_KEY=cursor_...
  .venv/bin/python agent/scripts/run_ca_data_repair_loop.py --max-runs 1
  .venv/bin/python agent/scripts/run_ca_data_repair_loop.py --max-runs 5 --model grok-4.5
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT = Path(__file__).resolve().parent / "prompts" / "ca_data_repair_next.txt"
SCRIPTS_ROOT = Path(__file__).resolve().parent


def jurisdiction_to_slug(name: str) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def script_path_for(state: str, jurisdiction: str) -> Path:
    state_l = state.strip().lower()
    city = jurisdiction_to_slug(jurisdiction)
    return SCRIPTS_ROOT / state_l / f"data_repair_{state_l}_{city}.py"


def first_missing_jurisdiction(
    parquet_path: Path,
) -> tuple[str, str] | None:
    """Return first (JURISDICTION, STATE) without a repair script, in parquet order."""
    import pandas as pd

    df = pd.read_parquet(parquet_path, columns=["JURISDICTION", "STATE"])
    pairs = df[["JURISDICTION", "STATE"]].drop_duplicates(keep="first")
    for _, row in pairs.iterrows():
        jurisdiction = str(row["JURISDICTION"])
        state = str(row["STATE"])
        if not script_path_for(state, jurisdiction).exists():
            return jurisdiction, state
    return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run sequential local Cursor agents for CA data repair."
    )
    p.add_argument(
        "--max-runs",
        type=int,
        default=1,
        help="Maximum number of agent runs (default: 1).",
    )
    p.add_argument(
        "--model",
        default=os.environ.get("CURSOR_MODEL", "grok-4.5"),
        help="Model id (default: grok-4.5 / Cursor Grok 4.5, or CURSOR_MODEL).",
    )
    p.add_argument(
        "--prompt-file",
        type=Path,
        default=DEFAULT_PROMPT,
        help="Path to the fixed prompt text file.",
    )
    p.add_argument(
        "--skip-exhaustion-check",
        action="store_true",
        help="Do not pre-check for missing jurisdictions before each run.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the next missing jurisdiction and exit without launching an agent.",
    )
    return p.parse_args()


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    args = parse_args()

    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not args.dry_run and not api_key:
        print(
            "CURSOR_API_KEY is not set. Create a key at "
            "https://cursor.com/dashboard/integrations and export it "
            "(or add it to .env).",
            file=sys.stderr,
        )
        return 1

    if args.max_runs < 1:
        print("--max-runs must be >= 1", file=sys.stderr)
        return 1

    prompt_path = args.prompt_file
    if not prompt_path.is_file():
        print(f"Prompt file not found: {prompt_path}", file=sys.stderr)
        return 1
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        print(f"Prompt file is empty: {prompt_path}", file=sys.stderr)
        return 1

    my_data = os.environ.get("MY_DATA_PATH")
    parquet_path = None
    if my_data:
        parquet_path = Path(my_data) / "processed_data" / "permits_ca_sample.parquet"

    if args.dry_run:
        print(f"repo={REPO_ROOT}")
        print(f"prompt={prompt_path}")
        print(f"MY_DATA_PATH={my_data}")
        if parquet_path is None:
            print("MY_DATA_PATH not set; cannot resolve next jurisdiction.", file=sys.stderr)
            return 1
        if not parquet_path.is_file():
            print(f"Parquet not found: {parquet_path}", file=sys.stderr)
            return 1
        print(f"parquet={parquet_path}")
        missing = first_missing_jurisdiction(parquet_path)
        if missing is None:
            print("No missing jurisdictions remain.")
            return 0
        jurisdiction, state = missing
        expected = script_path_for(state, jurisdiction)
        print(f"next_target={jurisdiction}, {state}")
        print(f"expected_script={expected.relative_to(REPO_ROOT)}")
        print(f"exists={expected.exists()}")
        return 0

    try:
        from cursor_sdk import Agent, CursorAgentError, LocalAgentOptions
    except ImportError:
        print(
            "cursor-sdk is not installed. Run:\n"
            "  .venv/bin/pip install cursor-sdk",
            file=sys.stderr,
        )
        return 1

    print(f"repo={REPO_ROOT}")
    print(f"model={args.model}")
    print(f"max_runs={args.max_runs}")
    print(f"prompt={prompt_path}")

    summaries: list[dict] = []

    for i in range(1, args.max_runs + 1):
        print(f"\n=== run {i}/{args.max_runs} ===")

        if not args.skip_exhaustion_check and parquet_path is not None:
            if not parquet_path.is_file():
                print(f"Parquet not found: {parquet_path}", file=sys.stderr)
                return 1
            missing = first_missing_jurisdiction(parquet_path)
            if missing is None:
                print("No missing jurisdictions remain; stopping.")
                break
            jurisdiction, state = missing
            expected = script_path_for(state, jurisdiction)
            print(f"next_target={jurisdiction}, {state}")
            print(f"expected_script={expected.relative_to(REPO_ROOT)}")

        started = time.monotonic()
        try:
            with Agent.create(
                model=args.model,
                api_key=api_key,
                local=LocalAgentOptions(
                    cwd=str(REPO_ROOT),
                    # Match interactive chats: load AGENTS.md / .cursor/rules.
                    setting_sources=["project"],
                ),
            ) as agent:
                agent_id = getattr(agent, "agent_id", None) or getattr(
                    agent, "agentId", None
                )
                print(f"agent_id={agent_id}")
                run = agent.send(prompt)
                run_id = getattr(run, "id", None)
                print(f"run_id={run_id}")
                result = run.wait()
        except CursorAgentError as err:
            elapsed = time.monotonic() - started
            print(
                f"startup failed after {elapsed:.1f}s: {err.message} "
                f"(retryable={err.is_retryable})",
                file=sys.stderr,
            )
            summaries.append(
                {
                    "run": i,
                    "status": "startup_error",
                    "elapsed_s": elapsed,
                    "error": str(err.message),
                }
            )
            _print_summary(summaries)
            return 1

        elapsed = time.monotonic() - started
        status = getattr(result, "status", None)
        print(f"status={status} elapsed_s={elapsed:.1f}")

        summaries.append(
            {
                "run": i,
                "status": status,
                "elapsed_s": elapsed,
                "run_id": run_id,
                "agent_id": agent_id,
            }
        )

        if status != "finished":
            print(
                f"Run ended with status={status}; stopping remaining runs.",
                file=sys.stderr,
            )
            _print_summary(summaries)
            return 2

    _print_summary(summaries)
    return 0


def _print_summary(summaries: list[dict]) -> None:
    print("\n=== summary ===")
    if not summaries:
        print("(no runs)")
        return
    for row in summaries:
        print(
            f"run={row['run']} status={row['status']} "
            f"elapsed_s={row['elapsed_s']:.1f} "
            f"agent_id={row.get('agent_id')} run_id={row.get('run_id')}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
