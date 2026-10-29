"""deploy/lock.sh: a killed deploy no longer blocks every later deploy (round 3 red team, rt3/h_lock.sh).

Each test runs the real lock.sh with HOME in a temp dir and remote() running the script locally, as the red team did.
"""
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = """
remote() {{ sh -c "$1"; }}
PA_DEPLOY_LOCK_WAIT={wait}
. "{root}/deploy/lock.sh"
deploy_lock "test deploy"
echo holding
sleep {hold}
"""


class DeployLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / "apps").mkdir()
        self.lock = self.home / "apps" / ".pa-deploy.lock.d"

    def deploy(self, hold=0, wait=2):
        return subprocess.Popen(["sh", "-c", DEPLOY.format(root=ROOT, wait=wait, hold=hold)], env={**os.environ, "HOME": str(self.home)},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def held(self, process):
        for line in process.stdout:
            if line.strip() == "holding":
                return
        self.fail("the first deploy never took the lock")

    def killed_deploy(self):
        first = self.deploy(hold=30)
        self.held(first)
        os.kill(first.pid, signal.SIGKILL)
        first.wait()
        self.assertTrue((self.lock / "owner").exists())
        return first

    def age_lock(self, minutes):
        pid, host, epoch = (self.lock / "owner.pid").read_text().split()
        (self.lock / "owner.pid").write_text(f"{pid} {host} {int(epoch) - minutes * 60}\n")

    def test_the_owner_pid_host_and_time_are_written(self):
        first = self.killed_deploy()
        pid, host, epoch = (self.lock / "owner.pid").read_text().split()
        self.assertEqual(int(pid), first.pid)
        self.assertTrue(host)
        self.assertLess(abs(int(epoch) - time.time()), 60)

    def test_a_killed_deploy_older_than_30_minutes_is_taken_over_loudly(self):
        self.killed_deploy()
        self.age_lock(31)
        out, err = self.deploy().communicate(timeout=30)
        self.assertIn("holding", out)
        self.assertIn("TAKING OVER", err)
        self.assertFalse(self.lock.exists())  # the new deploy released it on exit

    def test_a_young_lock_of_a_killed_deploy_still_waits(self):
        self.killed_deploy()
        self.age_lock(29)
        second = self.deploy()
        out, err = second.communicate(timeout=30)
        self.assertEqual(second.returncode, 75)
        self.assertNotIn("holding", out)

    def test_an_old_lock_whose_owner_still_runs_is_never_taken(self):
        first = self.deploy(hold=30)
        self.addCleanup(lambda: (first.kill(), first.wait()))
        self.held(first)
        self.age_lock(45)
        second = self.deploy()
        second.communicate(timeout=30)
        self.assertEqual(second.returncode, 75)

    def test_a_hand_made_lock_is_never_taken_over(self):
        self.lock.mkdir()
        old = time.time() - 3 * 3600
        os.utime(self.lock, (old, old))
        second = self.deploy()
        out, err = second.communicate(timeout=30)
        self.assertEqual(second.returncode, 75)
        self.assertTrue(self.lock.is_dir())
        self.assertNotIn("TAKING OVER", err)


if __name__ == "__main__":
    unittest.main()
