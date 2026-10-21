"""Linux supervisor for the existing browser and ranked operator launchers.

Never connects a second Playwright client, kills a live operator, or clears an
operator safety stop. SIGTERM stops supervision only, leaving play untouched.
"""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def option(args, name):
    for index, arg in enumerate(args):
        if arg.startswith(name + "="):
            return arg[len(name) + 1:]
        if arg == name and index + 1 < len(args):
            return args[index + 1]
    return None


def cdp_endpoint(value):
    parsed = urllib.parse.urlsplit(value)
    host = parsed.hostname
    if host in {"localhost", "127.0.0.1", "::1"}:
        host = "loopback"
    return host, parsed.port or (443 if parsed.scheme in {"https", "wss"} else 80)


def processes(root=ROOT, port=9222):
    """Adopt operators targeting this browser, including frozen checkouts."""
    found = {"operator": [], "launcher": [], "browser": [], "profile": []}
    profile = Path(os.environ.get("JANTAMA_BROWSER_PROFILE", root / ".runtime/browser-profile")).resolve()
    target = cdp_endpoint(f"http://127.0.0.1:{port}")
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = entry.joinpath("cmdline").read_bytes().decode().rstrip("\0").split("\0")
            cwd = entry.joinpath("cwd").resolve(strict=True)
            # Zombies have no cmdline and cannot still own a CDP connection.
            for kind, script in (("operator", "python/auto_operator.py"),
                                 ("launcher", "scripts/run-operator.mjs"),
                                 ("browser", "scripts/launch-browser.mjs")):
                exact = any(arg == str(root / script) or
                            (cwd == root and arg == script) for arg in args[1:])
                same_browser = False
                if kind in {"operator", "launcher"} and any(Path(arg).name == Path(script).name for arg in args[1:]):
                    same_browser = cdp_endpoint(option(args, "--cdp") or "http://127.0.0.1:9222") == target
                if exact or same_browser:
                    found[kind].append({"pid": int(entry.name), "args": args, "cwd": str(cwd)})
            if any(arg == f"--user-data-dir={profile}" for arg in args):
                found["profile"].append({"pid": int(entry.name)})
        except (OSError, UnicodeError, ValueError):
            continue
    return found


def cdp_ready(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:
            pages = json.load(response)
        return any(page.get("type") == "page" and
                   "mahjongsoul.com" in page.get("url", "") for page in pages)
    except (OSError, ValueError):
        return False


def terminal_event(log):
    if log is None or not log.exists():
        return None
    with log.open("rb") as stream:
        stream.seek(max(0, log.stat().st_size - 262144))
        lines = stream.read().decode(errors="replace").splitlines()
    terminal = None
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        event = row.get("event")
        if event == "started":
            terminal = None
        # Intentional exits include ranked navigation, login and dialog stops,
        # not just the original four stop names. Unknown future stop events
        # must also hold rather than silently becoming crash recovery.
        if isinstance(event, str) and event.endswith("_stop"):
            # A browser-close error during cleanup cannot erase an earlier
            # intentional stop in this same operator run.
            if terminal is None or restart_allowed(terminal) or not restart_allowed(row):
                terminal = row
    return terminal


def restart_allowed(terminal):
    if terminal is None:
        return True
    # This exact browser-close exception was observed during ranked play.
    return terminal.get("event") == "safety_stop" and \
        "Target page, context or browser has been closed" in terminal.get("error", "")


class Supervisor:
    def __init__(self, root, artifacts, layout, port=9222, clock=time.monotonic,
                 scan=None, ready=None, launch=None, match_length=None):
        self.root = root
        self.artifacts = artifacts
        self.layout = layout
        if match_length not in (None, "east"):
            raise ValueError("ranked supervisor selects East rooms; match length must be east or unspecified")
        self.match_length = match_length
        self.port = port
        self.clock = clock
        self.scan = scan or (lambda: processes(root, port))
        self.ready = ready or (lambda: cdp_ready(port))
        self.launch = launch or self.spawn
        self.last_operator = None
        self.operator_log = None
        self.next_start = 0
        self.attempts = {"browser": [], "operator": []}
        self.children = []
        self.hold_file = root / ".runtime/operator-supervisor-hold.json"
        self.state_file = root / ".runtime/operator-supervisor-state.json"
        if self.state_file.exists():
            # A supervisor restart must still inspect a stop that occurred
            # while it was offline; never silently discard the previous log.
            previous = json.loads(self.state_file.read_text())
            self.last_operator = previous.get("pid")
            if previous.get("log"):
                self.operator_log = Path(previous["log"])
        self.held = self.hold_file.exists()
        self.last_status = None
        artifacts.mkdir(parents=True, exist_ok=True)

    def log(self, event, **fields):
        row = {"timestamp": utc_now(), "event": event, **fields}
        with (self.artifacts / "supervisor.jsonl").open("a") as stream:
            stream.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)

    def status(self, event, **fields):
        state = (event, json.dumps(fields, sort_keys=True))
        if state != self.last_status:
            self.last_status = state
            self.log(event, **fields)

    def hold(self, reason, **fields):
        self.held = True
        self.hold_file.parent.mkdir(parents=True, exist_ok=True)
        self.hold_file.write_text(json.dumps({"timestamp": utc_now(), "reason": reason, **fields}, indent=2) + "\n")
        self.log("recovery_held", reason=reason, **fields)

    def spawn(self, kind, command, output):
        with output.open("ab") as stream:
            child = subprocess.Popen(command, cwd=self.root, stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        self.children.append(child)
        return child.pid

    def save_operator(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps({"pid": self.last_operator,
            "log": str(self.operator_log) if self.operator_log else None}) + "\n")
        temporary.replace(self.state_file)

    def tick(self):
        for child in self.children:
            child.poll()  # Reap exited launchers; never signal active children.
        state = self.scan()
        if len(state["operator"]) > 1:
            self.hold("multiple_operators", pids=[p["pid"] for p in state["operator"]])
            return
        if state["operator"]:
            operator = state["operator"][0]
            if operator["pid"] != self.last_operator:
                self.last_operator = operator["pid"]
                directory = option(operator["args"], "--artifacts") or "artifacts/python-auto"
                self.operator_log = self.root / directory / "operator-stdout.log"
                # The structured operator log is also available for operators
                # launched without stdout redirection.
                native = self.root / directory / "python-operator.jsonl"
                if native.exists():
                    self.operator_log = native
                self.save_operator()
                self.log("operator_adopted", pid=self.last_operator,
                         log=str(self.operator_log), args=operator["args"])
            self.status("operator_alive", pid=self.last_operator)
            return  # Never judge a live game by a CDP timeout or log silence.
        if state.get("launcher"):
            self.status("operator_launcher_waiting", pids=[p["pid"] for p in state["launcher"]])
            return
        if self.last_operator is not None:
            terminal = terminal_event(self.operator_log)
            self.log("operator_exited", pid=self.last_operator, terminal=terminal)
            self.last_operator = None
            if not restart_allowed(terminal):
                self.hold("operator_terminal_stop", terminal=terminal)
            self.save_operator()
            self.next_start = max(self.next_start, self.clock() + 10)
        if self.held:
            self.status("held", holdFile=str(self.hold_file))
            return
        if self.clock() < self.next_start:
            return
        healthy = self.ready()
        if not healthy and (state["browser"] or state["profile"]):
            self.status("browser_waiting", launchers=[p["pid"] for p in state["browser"]],
                        profiles=[p["pid"] for p in state["profile"]])
            return  # A slow/unresponsive browser is never killed or duplicated.
        kind = "operator" if healthy else "browser"
        self.attempts[kind] = [t for t in self.attempts[kind] if self.clock() - t < 600]
        if len(self.attempts[kind]) >= 3:
            self.hold("restart_limit", component=kind, attempts=len(self.attempts[kind]), windowSeconds=600)
            return
        # Bound component launches as well as operator-only crash loops.
        if not healthy:
            self.attempts[kind].append(self.clock())
            pid = self.launch("browser", ["node", "scripts/launch-browser.mjs"],
                              self.artifacts / "browser-stdout.log")
            self.log("browser_started", pid=pid)
            self.next_start = self.clock() + 10
            return
        # A normal first operator start and repeated operator-only crashes also
        # count, so a healthy CDP endpoint cannot cause an endless restart loop.
        self.attempts[kind].append(self.clock())
        run = self.artifacts / ("operator-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        run.mkdir(parents=True, exist_ok=True)
        args = ["node", "scripts/run-operator.mjs", "force-auto",
                f"--layout={self.layout}", f"--artifacts={run}",
                f"--cdp=http://127.0.0.1:{self.port}",
                "--action-deadline-ms=300000", "--force-auto-click-budget-ms=2600",
                "--board-metadata", "--advance-screens", "--ranked-loop", "--no-dashboard"]
        if self.match_length is not None:
            args.append(f"--match-length={self.match_length}")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root, text=True).strip()
        (run / "run-manifest.json").write_text(json.dumps({"status": "started", "commit": commit,
            "startedAt": utc_now(), "mode": "ranked", "actionDeadlineMs": 300000,
            "forceAutoClickBudgetMs": 2600, "rankedLoop": True,
            "matchLength": self.match_length, "command": args}, indent=2) + "\n")
        pid = self.launch("operator", args, run / "operator-stdout.log")
        self.operator_log = run / "operator-stdout.log"
        # Track even a launcher that exits before the next process scan, so
        # early safety-stop events cannot disappear without being inspected.
        self.last_operator = pid
        self.save_operator()
        self.log("operator_started", launcherPid=pid, artifacts=str(run), commit=commit)
        self.next_start = self.clock() + 10


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--layout", default="config/layout-300-regression.json")
    parser.add_argument("--match-length", choices=("east",), default=None,
                        help="verified current/queued East format; retained across operator restarts")
    parser.add_argument("--poll-seconds", type=float, default=5)
    args = parser.parse_args()
    if not Path("/proc/self/cmdline").exists():
        parser.error("Linux /proc is required for process adoption and duplicate prevention")
    if args.poll_seconds < 1:
        parser.error("--poll-seconds must be at least 1")
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    with (runtime / "operator-supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another supervisor holds the repository lock")
        supervisor = Supervisor(ROOT, (ROOT / args.artifacts).resolve(), args.layout,
                                port=int(os.environ.get("JANTAMA_CDP_PORT", "9222")),
                                match_length=args.match_length)
        stopping = False

        def stop(signum, frame):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        supervisor.log("supervisor_started", pid=os.getpid(), held=supervisor.held)
        while not stopping:
            supervisor.tick()
            time.sleep(args.poll_seconds)
        supervisor.log("supervisor_stopped", childrenLeftRunning=True)


if __name__ == "__main__":
    main()
