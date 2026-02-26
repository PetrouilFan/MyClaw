import asyncio, os, platform, uuid, signal
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

OUTPUT_DIR = Path("workspace/command_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_OUTPUT_LINES = 2000
MAX_PROCESSES = 1000
TRUNCATE_EVERY = 100

_processes: dict[int, dict] = {}
_loop: Optional[asyncio.AbstractEventLoop] = None
_executor = ThreadPoolExecutor(max_workers=4)
_truncate_counter: dict[str, int] = {}


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _loop.set_default_executor(_executor)
    return _loop


def _write_initial(filepath: str, command: str):
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] $ {command}\n")


def _write_output(filepath: str, text: str):
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(text)


def _truncate_file_safe(filepath: str, max_lines: int = MAX_OUTPUT_LINES):
    try:
        if not os.path.exists(filepath):
            return
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) > max_lines:
            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(lines[-max_lines:])
    except Exception:
        pass


async def run_command(
    command: str,
    background: bool = False,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: Optional[float] = None,
    on_complete: Optional[Callable[[int, int], None]] = None,
    on_output: Optional[Callable[[str], None]] = None,
) -> dict:
    if len(_processes) >= MAX_PROCESSES:
        return {"error": "Max processes reached", "max": MAX_PROCESSES}

    output_file = OUTPUT_DIR / f"{uuid.uuid4()}.log"
    output_path = str(output_file)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _write_initial, output_path, command)

    env_vars = env or {}
    full_env = {**os.environ, **env_vars}

    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
        env=full_env,
    )

    proc_info = {
        "pid": process.pid,
        "command": command,
        "output_file": output_path,
        "started_at": datetime.now().isoformat(),
        "status": "running",
        "return_code": None,
        "process": process,
        "on_complete": on_complete,
        "on_output": on_output,
        "line_count": 0,
    }

    _processes[process.pid] = proc_info
    _truncate_counter[output_path] = 0

    async def stream_output():
        try:
            if process.stdout:
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace")
                    await loop.run_in_executor(None, _write_output, output_path, text)
                    proc_info["line_count"] += 1
                    _truncate_counter[output_path] = (
                        _truncate_counter.get(output_path, 0) + 1
                    )
                    if _truncate_counter[output_path] >= TRUNCATE_EVERY:
                        await loop.run_in_executor(
                            None, _truncate_file_safe, output_path
                        )
                        _truncate_counter[output_path] = 0
                    if on_output:
                        try:
                            on_output(text)
                        except Exception:
                            pass

            return_code = await process.wait()
            proc_info["return_code"] = return_code
            proc_info["status"] = "completed" if return_code == 0 else "failed"

            if on_complete:
                try:
                    on_complete(process.pid, return_code)
                except Exception:
                    pass
        except Exception:
            proc_info["status"] = "failed"

    if background:
        asyncio.create_task(stream_output())
        return {
            "pid": process.pid,
            "output_file": output_path,
            "status": "started",
            "command": command,
        }

    await stream_output()
    return {
        "pid": process.pid,
        "output_file": output_path,
        "status": proc_info["status"],
        "return_code": proc_info["return_code"],
        "command": command,
    }


async def wait_command(process_id: int, timeout: Optional[float] = None) -> dict:
    proc_info = _processes.get(process_id)
    if not proc_info:
        return {"error": f"Process {process_id} not found", "exists": False}

    process = proc_info["process"]

    try:
        if timeout:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        else:
            await process.wait()

        proc_info["return_code"] = process.returncode
        proc_info["status"] = "completed" if process.returncode == 0 else "failed"

        return {
            "pid": process_id,
            "return_code": process.returncode,
            "status": proc_info["status"],
            "output_file": proc_info["output_file"],
        }
    except asyncio.TimeoutError:
        return {"error": "Timeout waiting for process", "status": "timeout"}


async def kill_command(process_id: int) -> dict:
    proc_info = _processes.get(process_id)
    if not proc_info:
        return {"error": f"Process {process_id} not found", "exists": False}

    process = proc_info["process"]

    try:
        if platform.system() == "Windows":
            process.terminate()
        else:
            process.send_signal(signal.SIGTERM)

        proc_info["status"] = "terminated"
        return {
            "pid": process_id,
            "status": "terminated",
            "output_file": proc_info["output_file"],
        }
    except Exception as e:
        return {"error": str(e)}


def read_output(process_id: int, lines: int = 100, from_start: bool = False) -> dict:
    proc_info = _processes.get(process_id)
    if not proc_info:
        return {"error": f"Process {process_id} not found", "exists": False}

    output_file = proc_info["output_file"]

    if not os.path.exists(output_file):
        return {"error": "Output file not found", "output_file": output_file}

    try:
        with open(output_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        selected = (
            all_lines[:lines]
            if from_start
            else (all_lines[-lines:] if len(all_lines) > lines else all_lines)
        )

        return {
            "pid": process_id,
            "lines": len(selected),
            "total_lines": len(all_lines),
            "output": "".join(selected),
            "output_file": output_file,
        }
    except Exception as e:
        return {"error": str(e)}


def cleanup_processes(keep_running: bool = True) -> int:
    removed = 0
    to_remove = [
        pid
        for pid, info in _processes.items()
        if info["status"] != "running" or not keep_running
    ]
    for pid in to_remove:
        del _processes[pid]
        removed += 1
    return removed


def list_processes(status_filter: Optional[str] = None) -> dict:
    processes = [
        {
            "pid": pid,
            "command": info["command"],
            "status": info["status"],
            "started_at": info["started_at"],
            "output_file": info["output_file"],
        }
        for pid, info in _processes.items()
        if status_filter is None or info["status"] == status_filter
    ]
    return {"processes": processes, "total": len(processes)}


def run_terminal_command(
    command: str,
    background: bool = False,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> dict:
    return _get_loop().run_until_complete(
        run_command(
            command=command, background=background, cwd=cwd, env=env, timeout=timeout
        )
    )


def wait_terminal_command(process_id: int, timeout: Optional[float] = None) -> dict:
    return _get_loop().run_until_complete(
        wait_command(process_id=process_id, timeout=timeout)
    )


def kill_terminal_command(process_id: int) -> dict:
    return _get_loop().run_until_complete(kill_command(process_id=process_id))


def list_terminal_commands(status_filter: Optional[str] = None) -> dict:
    return list_processes(status_filter)


def cleanup_terminal_processes(keep_running: bool = True) -> dict:
    removed = cleanup_processes(keep_running)
    return {"removed": removed, "remaining": len(_processes)}


def get_terminal_help() -> dict:
    help_path = Path("workspace/terminal_help.md")
    if help_path.exists():
        return {"usage_guide": help_path.read_text(encoding="utf-8")}
    return {"usage_guide": "See workspace/terminal_help.md for usage guide"}


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_terminal_command",
            "description": "Execute a terminal command. Supports parallel execution - call multiple times with background=true to run commands concurrently. Returns PID for tracking. Output is buffered to file (max 2000 lines). Use read_command_output with PID to read output while running or after completion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command to execute (Windows: cmd.exe commands, Linux: sh commands)",
                    },
                    "background": {
                        "type": "boolean",
                        "description": "Run in background without waiting. Use this for parallel execution - start multiple commands, then use wait_command to wait for specific ones.",
                        "default": False,
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory for the command",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Max execution time in seconds. Only applies when background=false",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_terminal_command",
            "description": "Wait for a background command to complete. Use the PID returned from run_terminal_command. Returns status, return_code, and output_file path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "integer",
                        "description": "The process ID (PID) returned from run_terminal_command",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Max time to wait in seconds. Returns 'timeout' status if exceeded",
                    },
                },
                "required": ["process_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_command_output",
            "description": "Read output from a running or completed command. Use lines=100 (default) to get last 100 lines - works while command is still running. Use from_start=true to read from beginning. Output is buffered to workspace/command_outputs/{uuid}.log",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "integer",
                        "description": "The process ID (PID) from run_terminal_command",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of lines to read. Use smaller values for faster reads while command runs.",
                        "default": 100,
                    },
                    "from_start": {
                        "type": "boolean",
                        "description": "Read from beginning instead of tail. Useful for checking full output of short commands.",
                        "default": False,
                    },
                },
                "required": ["process_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kill_terminal_command",
            "description": "Kill a running command process. Use when command hangs or you need to cancel it. Returns final status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "integer",
                        "description": "The process ID (PID) to kill",
                    }
                },
                "required": ["process_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_terminal_commands",
            "description": "List all tracked command processes. Use status_filter to filter: 'running', 'completed', 'failed', 'terminated'. Returns PID, command, status, output_file for each.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status_filter": {
                        "type": "string",
                        "description": "Filter by status: 'running', 'completed', 'failed', 'terminated'. Omit for all processes.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cleanup_terminal_processes",
            "description": "Clean up completed/failed/terminated processes from memory. Call periodically when running many background commands to prevent memory buildup. Does not affect running processes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keep_running": {
                        "type": "boolean",
                        "description": "If true, keeps running processes. If false, removes all including running.",
                        "default": True,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_terminal_help",
            "description": "Get detailed usage guide for terminal command tools. Includes parallel execution patterns, examples, and best practices.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

TOOL_FUNCTIONS = {
    "run_terminal_command": run_terminal_command,
    "wait_terminal_command": wait_terminal_command,
    "read_command_output": read_output,
    "kill_terminal_command": kill_terminal_command,
    "list_terminal_commands": list_terminal_commands,
    "cleanup_terminal_processes": cleanup_terminal_processes,
    "get_terminal_help": get_terminal_help,
}
