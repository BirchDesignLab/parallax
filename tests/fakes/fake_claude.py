"""Stand-in for the claude CLI. Records argv and stdin, then replays the stream shapes the real CLI produced."""
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
record = Path(os.environ["FAKE_CLAUDE_RECORD"])
calls = json.loads(record.read_text()) if record.exists() else []
calls.append({"argv": args, "stdin": sys.stdin.read() if args[0] != "purge" else "", "cwd": os.getcwd(),
              "env": sorted(k for k in os.environ if k.startswith(("CLAUDE", "ANTHROPIC", "OPENAI", "CODEX")))})
record.write_text(json.dumps(calls))
if args[0] == "purge":
    sys.exit(0)
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
session = args[args.index("--session-id") + 1] if "--session-id" in args else args[args.index("--resume") + 1]
usage = {"input_tokens": 12, "cache_creation_input_tokens": 300, "cache_read_input_tokens": 9000, "output_tokens": 45}
print(json.dumps({"type": "system", "subtype": "init", "cwd": os.getcwd(), "model": "claude-fable-5-2",
                  "permissionMode": "acceptEdits", "tools": ["Edit", "Glob", "Grep", "Read", "Write"]}))
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "tests/test_clamp.py"}}]}}))
result = {"type": "result", "subtype": "success", "is_error": False, "session_id": session, "usage": usage, "num_turns": 2}
if mode == "ok":
    result.update(result="done", structured_output={"summary": "probed", "blocked": "", "files": []})
elif mode == "text_json":
    result.update(result='{"summary": "probed", "blocked": "", "files": []}')
elif mode == "wrong_shape":
    result.update(result="done", structured_output={"summary": "probed"})
elif mode == "auth":
    result.update(is_error=True, result="Failed to authenticate: OAuth session expired and could not be refreshed")
if mode != "no_result":
    print(json.dumps(result))
sys.exit(1 if mode in ("auth", "no_result") else 0)
