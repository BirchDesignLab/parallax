"""Stand-in for the codex CLI. Records its argv and stdin, then replays the event shapes the real CLI produced."""
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
record = Path(os.environ["FAKE_CODEX_RECORD"])
calls = json.loads(record.read_text()) if record.exists() else []
calls.append({"argv": args, "stdin": sys.stdin.read(), "cwd": os.getcwd(),
              "env": sorted(k for k in os.environ if k.startswith(("CLAUDE", "ANTHROPIC", "OPENAI", "CODEX")))})
record.write_text(json.dumps(calls))
if args[0] == "delete":
    print(f"Deleted session {args[-1]}.")
    sys.exit(0)
mode = os.environ.get("FAKE_CODEX_MODE", "ok")
if mode == "launch_failure" and len(calls) == 1:
    print('CreateProcessWithLogonW failed: 1056', file=sys.stderr)
    sys.exit(1)
if mode == "always_fails":
    print("boom", file=sys.stderr)
    sys.exit(2)
print(json.dumps({"type": "thread.started", "thread_id": "01a1e764-ff34-76b3-ba77-7b4c3f751503"}))
print(json.dumps({"type": "turn.started"}))
print(json.dumps({"type": "item.completed", "item": {"id": "item_0", "type": "command_execution", "command": "powershell.exe -Command dir",
                                                       "aggregated_output": "ok", "exit_code": 0, "status": "completed"}}))
last = {"ok": '{"summary": "probed", "blocked": "", "files": []}', "launch_failure": '{"summary": "probed", "blocked": "", "files": []}',
        "not_json": "I could not do that.", "wrong_shape": '{"summary": "probed"}'}[mode]
print(json.dumps({"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": last}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 31830, "cached_input_tokens": 15488, "cache_write_input_tokens": 0,
                                                       "output_tokens": 295, "reasoning_output_tokens": 0}}))
Path(args[args.index("-o") + 1]).write_text(last, encoding="utf-8")
