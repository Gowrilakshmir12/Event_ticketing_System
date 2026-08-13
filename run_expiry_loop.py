"""
Runs the hold-expiry sweep every 30 seconds. For local dev/demo only —
in production this would be a cron job or scheduled task instead.
"""
import subprocess
import sys
import time

while True:
    subprocess.run([sys.executable, "manage.py", "expire_holds"])
    time.sleep(30)