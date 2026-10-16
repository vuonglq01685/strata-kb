import json
import os
import sys
from pathlib import Path

# Stand-in for `claude -p`. FAKE_CLAUDE_REPLIES names a JSON list; each call
# consumes the next entry (position kept in <replies>.pos) and appends its
# argv/cwd/stdin to <replies>.calls. A str entry becomes a result envelope; a
# dict is printed as the envelope, except "_exit"/"_stderr" which set the exit
# code and stderr.
replies_path = Path(os.environ["FAKE_CLAUDE_REPLIES"])
pos_path = Path(str(replies_path) + ".pos")
calls_path = Path(str(replies_path) + ".calls")

stdin = sys.stdin.read()
with calls_path.open("a", encoding="utf-8") as fh:
    fh.write(
        json.dumps(
            {
                "argv": sys.argv[1:],
                "cwd": os.getcwd(),
                "stdin": stdin,
                "auto_task": os.environ.get("STRATA_KB_AUTO_TASK"),
            }
        )
    )
    fh.write("\n")

replies = json.loads(replies_path.read_text(encoding="utf-8"))
pos = int(pos_path.read_text()) if pos_path.exists() else 0
pos_path.write_text(str(pos + 1))
entry = replies[pos]
if isinstance(entry, str):
    entry = {"type": "result", "result": entry}
code = entry.pop("_exit", 0)
sys.stderr.write(entry.pop("_stderr", ""))
sys.stdout.write(json.dumps(entry) + "\n")
sys.exit(code)
