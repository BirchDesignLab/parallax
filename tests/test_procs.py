import sys, tempfile, time, unittest
from pathlib import Path
from parallax.procs import run_command

class RunCommand(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp(prefix="plx proc "))

    def test_captures_both_streams_and_the_exit_code(self):
        result = run_command([sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"], self.cwd, 30)
        self.assertEqual((result.code, result.timed_out), (3, False))
        self.assertIn("out", result.output); self.assertIn("err", result.output)

    def test_shell_string_and_stdin(self):
        result = run_command(f'"{sys.executable}" -c "import sys; print(sys.stdin.read().upper())"', self.cwd, 30, input="hello")
        self.assertIn("HELLO", result.output)

    def test_timeout_kills_the_whole_tree(self):
        marker = self.cwd / "grandchild was here.txt"
        child = f"import time, pathlib; time.sleep(4); pathlib.Path(r'{marker}').write_text('x')"
        parent = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(60)"
        started = time.time()
        result = run_command([sys.executable, "-c", parent], self.cwd, 1)
        self.assertTrue(result.timed_out); self.assertIsNone(result.code)
        self.assertLess(time.time() - started, 20)
        time.sleep(6)
        self.assertFalse(marker.exists())
