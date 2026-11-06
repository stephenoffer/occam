"""Hand finished rollups to the billing uplink."""

import subprocess
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "push-rollups"


def push(data_dir, source, label):
    """Deliver everything in rollups/<source>/. Raises CalledProcessError if the tool fails."""
    rollups = Path(data_dir) / "rollups" / source
    done = subprocess.run([str(TOOL), "--source", source, "--label", label, str(rollups)],
                          capture_output=True, text=True)
    with (Path(data_dir) / "push.log").open("a") as log:
        log.write(done.stdout + done.stderr)
    done.check_returncode()
