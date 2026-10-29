"""The public images hold only the files their Dockerfile copies. The service must start from exactly those files.

On Oct 28 the families service started to use parenting_agent/cry_reason.py, the image did not copy it, and the deploy
failed its health check and rolled back. These tests copy what each Dockerfile copies into an empty folder and import
the service from there, in a fresh isolated interpreter.
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGES = {"families": ("parenting_agent.families.service", "parenting_agent.families.__main__",
                       "parenting_agent.families.export_sessions", "parenting_agent.families.bot"),
          "voice": ("parenting_agent.voice.server", "parenting_agent.voice.client", "parenting_agent.voice.tts"),
          "demo": ("parenting_agent.demo.app", "parenting_agent.demo.__main__", "parenting_agent.demo.export_sessions")}


def copied(dockerfile, into):
    for line in dockerfile.read_text().splitlines():
        if not line.startswith("COPY "):
            continue
        *sources, dest = line.split()[1:]
        for source in sources:
            path, target = ROOT / source, into / dest
            if path.is_dir():
                shutil.copytree(path, target, dirs_exist_ok=True)
            else:
                (target if dest.endswith("/") else target.parent).mkdir(parents=True, exist_ok=True)
                shutil.copy(path, target / path.name if dest.endswith("/") else target)


class Images(unittest.TestCase):
    def test_each_service_imports_from_its_image_files_only(self):
        for name, modules in IMAGES.items():
            with self.subTest(image=name):
                folder = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, folder, True)
                copied(ROOT / "deploy" / name / "Dockerfile", folder)
                code = "import importlib, sys\nsys.path.insert(0, sys.argv[1])\nfor m in sys.argv[2:]: importlib.import_module(m)"
                run = subprocess.run([sys.executable, "-I", "-c", code, str(folder), *modules], cwd=folder,
                                     capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
