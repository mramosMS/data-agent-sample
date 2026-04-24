import argparse
import asyncio
import itertools
import logging
import sys
import threading
import time

import uvicorn

logging.basicConfig(level=logging.INFO)


def _spinner(stop_event: threading.Event, message: str = "Working") -> None:
    """Spin a small ASCII indicator on the current line until stop_event is set."""
    frames = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    while not stop_event.is_set():
        sys.stdout.write(f"\r{message} {next(frames)} ")
        sys.stdout.flush()
        stop_event.wait(0.1)
    # Clear the spinner line so the agent answer starts cleanly
    sys.stdout.write("\r" + " " * (len(message) + 4) + "\r")
    sys.stdout.flush()


async def interactive_console() -> None:
    from src.application.agent_runner import run_query
    from src.tools.fabric_data_agent_http_tool import get_last_run_data

    print("Trucking Agent — interactive console. Type 'exit' or 'quit' to stop.\n")
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            print("Bye!")
            break

        stop = threading.Event()
        spinner = threading.Thread(target=_spinner, args=(stop, "Thinking"), daemon=True)
        spinner.start()
        t_start = time.perf_counter()
        try:
            answer = await run_query(question)
        except Exception as exc:
            elapsed = time.perf_counter() - t_start
            stop.set()
            spinner.join()
            print(f"\n[error] {exc}  ({elapsed:.1f}s)\n")
            continue
        finally:
            stop.set()
        spinner.join()
        elapsed = time.perf_counter() - t_start

        print(f"\nAgent: {answer}\n")

        run_data = get_last_run_data()
        if run_data:
            _print_run_details(run_data, elapsed)


def _print_run_details(run_data: dict, elapsed: float = 0.0) -> None:
    """Print a formatted run-details block (steps + SQL + data previews) after the agent answer."""
    from src.tools.fabric_data_agent_http_tool import _format_steps

    sep = "─" * 60
    print(sep)
    print(f"  Run status : {run_data.get('run_status', 'unknown')}")
    print(f"  Time taken : {elapsed:.2f}s")

    steps_dump = run_data.get("run_steps", {})
    step_lines = _format_steps(steps_dump)
    if step_lines:
        print("  Steps:")
        for line in step_lines:
            print(f"  {line}")

    sql_queries = run_data.get("sql_queries", [])
    sql_data_previews = run_data.get("sql_data_previews", [])
    if sql_queries:
        print("  SQL Queries:")
        for i, q in enumerate(sql_queries, start=1):
            print(f"    [{i}] {q}")
            # Show the data preview paired with this query when available
            if i - 1 < len(sql_data_previews):
                preview = sql_data_previews[i - 1]
                if preview:
                    print("    Data preview:")
                    lines = preview if isinstance(preview, list) else str(preview).splitlines()
                    for row in lines[:10]:
                        print(f"      {row}")
                    if len(lines) > 10:
                        print(f"      ... ({len(lines) - 10} more rows)")

    print(f"{sep}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trucking Agent")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the HTTP API server instead of the interactive console.",
    )
    args = parser.parse_args()

    if args.serve:
        uvicorn.run("src.api.app:app", host="127.0.0.1", port=8200, reload=False)
    else:
        asyncio.run(interactive_console())
