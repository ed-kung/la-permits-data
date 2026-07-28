#!/usr/bin/env python3
"""Sequentially launch fresh local Cursor agents for CA data-repair work.

Each iteration uses a new Agent (clear context) with the fixed prompt in
prompts/ca_data_repair_next.txt. The agent chooses the next jurisdiction.
Requires CURSOR_API_KEY.

After each finished agent run, stages new/changed repair scripts and reports
with `git add` (does not commit).

Usage:
  export CURSOR_API_KEY=cursor_...
  .venv/bin/python agent/scripts/run_ca_data_repair_loop.py --max-runs 1
  .venv/bin/python agent/scripts/run_ca_data_repair_loop.py --max-runs 5 --model grok-4.5
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT = Path(__file__).resolve().parent / "prompts" / "ca_data_repair_next.txt"

# Pathspecs for artifacts agents create; never commit from this script.
ARTIFACT_PATHSPECS = (
    ":(glob)agent/scripts/**/data_repair_*.py",
    ":(glob)agent/scripts/data_repair_*.py",
    ":(glob)agent/reports/*.md",
)


def _paths_needing_stage(pathspecs: tuple[str, ...] | list[str]) -> list[str]:
    """Repo-relative paths under pathspecs that are untracked or have unstaged changes."""
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", *pathspecs],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    paths: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        xy, rest = line[:2], line[3:]
        path = rest.split(" -> ", 1)[-1] if " -> " in rest else rest
        # Untracked, or worktree column dirty (needs git add).
        if xy == "??" or (len(xy) > 1 and xy[1] != " "):
            paths.append(path)
    return paths


def stage_repair_artifacts() -> list[str]:
    """`git add` repair scripts and reports; do not commit. Returns staged paths."""
    candidates = _paths_needing_stage(ARTIFACT_PATHSPECS)
    if not candidates:
        print("git: no new repair scripts/reports to stage")
        return []

    proc = subprocess.run(
        ["git", "add", "--", *ARTIFACT_PATHSPECS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        print(f"git add failed: {err}", file=sys.stderr)
        return []

    print(f"git: staged {len(candidates)} path(s) (no commit):")
    for path in candidates:
        print(f"  {path}")
    return candidates


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run sequential local Cursor agents for CA data repair."
    )
    p.add_argument(
        "--max-runs",
        type=int,
        default=1,
        help="Number of agent runs (default: 1).",
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
        "--dry-run",
        action="store_true",
        help="Print run config and exit without launching an agent.",
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

    print(f"repo={REPO_ROOT}")
    print(f"model={args.model}")
    print(f"max_runs={args.max_runs}")
    print(f"prompt={prompt_path}")

    if args.dry_run:
        print("dry_run=True (not launching agents)")
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

    summaries: list[dict] = []

    for i in range(1, args.max_runs + 1):
        print(f"\n=== run {i}/{args.max_runs} ===")

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

        staged = stage_repair_artifacts()

        summaries.append(
            {
                "run": i,
                "status": status,
                "elapsed_s": elapsed,
                "run_id": run_id,
                "agent_id": agent_id,
                "staged": staged,
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
        staged = row.get("staged") or []
        if staged:
            print(f"  staged={len(staged)}: {', '.join(staged)}")


if __name__ == "__main__":
    raise SystemExit(main())
