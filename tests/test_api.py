#!/usr/bin/env python
"""Test Flask API startup and response."""
import os
import sys

# Load env vars
with open("docker-deploy/.env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ[key] = val

sys.path.insert(0, ".")

from api.server import app
from werkzeug.serving import make_server
import threading
import time
import requests

# Start server
server = make_server("127.0.0.1", 8000, app)
thread = threading.Thread(target=server.serve_forever)
thread.daemon = True
thread.start()

time.sleep(2)

try:
    r = requests.get("http://127.0.0.1:8000/api/v1/system/ready", timeout=5)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text[:300]}")
except Exception as e:
    print(f"Error: {e}")
finally:
    server.shutdown()
