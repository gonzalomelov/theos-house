"""The demo and families images copy only some modules (deploy/*/Dockerfile). A message that reaches code outside them
crashed the live demo with a 502 after blind round b7 ("No module named parenting_agent.night_feed"). This builds the
demo's file set as its Dockerfile does and sends the b7 messages through it."""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = """
import datetime
from parenting_agent.demo.app import DemoApp, TZ
from parenting_agent.demo.settings import load
clock = {"now": datetime.datetime(2026, 11, 2, 4, 30, tzinfo=TZ)}
import tempfile
app = DemoApp(load({"PA_DEMO_BRAIN": "fake", "PA_DEMO_DATA_DIR": tempfile.mkdtemp(), "PA_DEMO_PORT": "0"}), clock=lambda: clock["now"])
for text, lang in (("he just woke up crying", "en"), ("se despertó llorando", "es"), ("he napped about 40 minutes", "en"),
                   ("quedó dormido", "es"), ("how many feeds since 22:00?", "en"),
                   ("Did the microphone hear him cry?", "en"), ("vacuum over the sleeping baby", "en")):
    status, body = app.message("v", True, text, lang=lang)
    assert status == 200, (text, status, body)
print("ok")
"""


def copied(dockerfile):
    paths = []
    for line in dockerfile.read_text().splitlines():
        match = re.match(r"COPY\s+(.+)\s+\S+$", line)
        if match and "--from" not in line:
            paths += match.group(1).split()
    return paths


class DemoImageImports(unittest.TestCase):
    def test_the_b7_messages_run_with_only_the_demo_image_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rel in copied(ROOT / "deploy" / "demo" / "Dockerfile"):
                src, dst = ROOT / rel, Path(tmp) / rel
                if not src.exists():
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                (shutil.copytree if src.is_dir() else shutil.copy)(src, dst)
            run = subprocess.run([sys.executable, "-c", SCRIPT], cwd=tmp, capture_output=True, text=True, timeout=120,
                                 env={"PATH": "/usr/bin:/bin", "PYTHONPATH": tmp})
            self.assertEqual(run.returncode, 0, run.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
