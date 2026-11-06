"""Hand finished rollups to the billing uplink."""

import subprocess
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "push-rollups"


def push(data_dir, source, label):
    """Deliver everything in rollups/<source>/, keeping a log of what the tool said. Raises if delivery fails."""
    rollups = Path(data_dir) / "rollups" / source
    log = Path(data_dir) / "push.log"
    with log.open("a") as handle:
        subprocess.run([str(TOOL), "--source", source, "--label", label, str(rollups)],
                       stdout=handle, stderr=subprocess.STDOUT)
