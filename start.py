#!/usr/bin/env python3
"""MyClaw Launcher - Central process manager and gateway."""

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from rich.console import Console
from rich.logging import RichHandler
from typing import Any

PROJECT_ROOT = Path(__file__).parent.resolve()
LOGS_DIR = PROJECT_ROOT / "logs"
PID_FILE = LOGS_DIR / "myclaw.pid"
console = Console()


@dataclass
class ChannelSpec:
    """Defines a service that can be launched."""

    name: str
    script: Path
    enabled: bool = True
    env: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)


DEFAULT_CHANNELS = [
    ChannelSpec(
        "myclaw",
        PROJECT_ROOT / "myclaw.py",
        enabled=True,
    ),
    ChannelSpec(
        "telegram",
        PROJECT_ROOT / "channels" / "telegram_bot.py",
        enabled=True,
    ),
]


def rotate_logs() -> None:
    """Rotate logs: keep last 2 logs (current + 1 backup)."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    main_log = LOGS_DIR / "myclaw.log"
    backup_log = LOGS_DIR / "myclaw.log.1"

    try:
        if backup_log.exists():
            backup_log.unlink()

        if main_log.exists():
            main_log.rename(backup_log)
    except PermissionError:
        pass


def setup_logging(level: str = "INFO") -> None:
    """Configure centralized logging with rich console output."""
    log_level = getattr(logging, level.upper())

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                tracebacks_show_locals=True,
                show_time=True,
                show_path=False,
            ),
            logging.FileHandler(LOGS_DIR / "myclaw.log"),
        ],
    )


class ProcessManager:
    """Manages MyClaw processes."""

    def __init__(self, channels: list[ChannelSpec]):
        self.channels = {ch.name: ch for ch in channels}
        self.processes: dict[str, subprocess.Popen] = {}
        self.logger = logging.getLogger("ProcessManager")

    def start_channel(self, spec: ChannelSpec) -> bool:
        """Start a single channel process."""
        if not spec.script.exists():
            self.logger.error(f"Script not found: {spec.script}")
            return False

        env = os.environ.copy()
        env.update(spec.env)

        try:
            log_file = open(LOGS_DIR / f"{spec.name}.out.log", "a")
            proc = subprocess.Popen(
                [sys.executable, str(spec.script)],
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            log_file.close()
            self.processes[spec.name] = proc
            self.logger.info(f"Started {spec.name} (PID: {proc.pid})")
            return True
        except Exception as e:
            self.logger.error(f"Failed to start {spec.name}: {e}")
            return False

    def stop_channel(self, name: str) -> bool:
        """Stop a single channel gracefully."""
        if name not in self.processes:
            self.logger.warning(f"Process {name} not running")
            return False

        proc = self.processes[name]

        try:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            self.logger.info(f"Stopped {name}")
            del self.processes[name]
            return True
        except Exception as e:
            self.logger.error(f"Error stopping {name}: {e}")
            return False

    def start_all(self, enabled_only: bool = True) -> bool:
        """Start all enabled channels in order (myclaw first)."""
        to_start = (
            [ch for ch in DEFAULT_CHANNELS if ch.enabled] if enabled_only else DEFAULT_CHANNELS
        )

        myclaw_ch = next((ch for ch in to_start if ch.name == "myclaw"), None)
        other_chs = [ch for ch in to_start if ch.name != "myclaw"]

        if myclaw_ch:
            if not self.start_channel(myclaw_ch):
                self.logger.error("Failed to start myclaw, channels may not work properly")
                return False
            time.sleep(2)

        for ch in other_chs:
            if not self.start_channel(ch):
                self.logger.warning(f"Failed to start {ch.name}, continuing...")

        self.save_pids()
        return True

    def stop_all(self) -> None:
        """Stop all running processes."""
        for name in list(self.processes.keys()):
            self.stop_channel(name)
        self.save_pids()

    def save_pids(self) -> None:
        """Save process PIDs to file."""
        with open(PID_FILE, "w") as f:
            for name, proc in self.processes.items():
                f.write(f"{name}:{proc.pid}\n")

    def get_status(self) -> dict:
        """Get status of all processes."""
        status = {}
        for name, proc in self.processes.items():
            status[name] = "running" if proc.poll() is None else "dead"
        return status

    def monitor_loop(self, check_interval: int = 5) -> None:
        """Monitor processes and auto-restart on crash."""
        self.logger.info("Entering monitor mode...")

        while self.processes:
            for name, proc in list(self.processes.items()):
                if proc.poll() is not None:
                    self.logger.warning(f"{name} crashed, restarting...")
                    spec = self.channels.get(name)
                    if spec:
                        self.start_channel(spec)

            time.sleep(check_interval)


def list_channels() -> None:
    """List all available channels."""
    print("Available channels:")
    for ch in DEFAULT_CHANNELS:
        status = "enabled" if ch.enabled else "disabled"
        print(f"  - {ch.name}: {ch.script} [{status}]")


def stop_via_pid() -> None:
    """Stop processes using PID file."""
    if not PID_FILE.exists():
        print("No PID file found, nothing to stop")
        return

    with open(PID_FILE) as f:
        for line in f:
            if ":" in line:
                name, pid = line.strip().split(":")
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    print(f"Sent SIGTERM to {name} (PID: {pid})")
                except ProcessLookupError:
                    print(f"Process {name} (PID: {pid}) not found")
                except PermissionError:
                    print(f"Permission denied to kill {name} (PID: {pid})")

    PID_FILE.unlink()
    print("Stop signal sent to all processes")


def show_status(manager: ProcessManager) -> None:
    """Show status of all processes."""
    status = manager.get_status()
    if not status:
        print("No processes running")
        return

    print("Process status:")
    for name, state in status.items():
        print(f"  - {name}: {state}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MyClaw Launcher")
    parser.add_argument("--list", action="store_true", help="List available channels")
    parser.add_argument("--no-channels", action="store_true", help="Skip starting channel bots")
    parser.add_argument("--channel", action="append", help="Enable a specific channel (can repeat)")
    parser.add_argument("--exclude", action="append", help="Exclude a channel (can repeat)")
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Enable crash monitoring with auto-restart",
    )
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    parser.add_argument("--stop", action="store_true", help="Stop all running processes")
    parser.add_argument("--status", action="store_true", help="Show status of all processes")

    args = parser.parse_args()

    rotate_logs()
    setup_logging(args.log_level)
    logger = logging.getLogger("main")

    if args.list:
        list_channels()
        return

    if args.stop:
        stop_via_pid()
        return

    enabled_channels = []
    for ch in DEFAULT_CHANNELS:
        if ch.name == "myclaw":
            enabled_channels.append(ch)
        elif args.no_channels:
            continue
        elif args.channel and ch.name not in args.channel:
            continue
        elif args.exclude and ch.name in args.exclude:
            continue
        else:
            enabled_channels.append(ch)

    manager = ProcessManager(enabled_channels)

    if args.status:
        show_status(manager)
        return

    logger.info("=" * 50)
    logger.info("Starting MyClaw Launcher")
    logger.info(f"Channels: {[ch.name for ch in enabled_channels]}")
    logger.info("=" * 50)

    if not manager.start_all(enabled_only=False):
        logger.error("Failed to start processes")
        sys.exit(1)

    def signal_handler(signum: int, frame: Any) -> None:
        logger.info(f"Received signal {signum}, shutting down...")
        manager.stop_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.monitor:
        try:
            manager.monitor_loop()
        except KeyboardInterrupt:
            logger.info("Monitor loop interrupted")
            manager.stop_all()
    else:
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
