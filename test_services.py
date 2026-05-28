"""Test script to verify all services can start."""
import sys
sys.path.insert(0, '.')

from config import get_config

print("=" * 50)
print("AntiBlack Service Startup Test")
print("=" * 50)

# 1. Config
print("\n[1] Testing config...")
config = get_config()
print(f"    Config loaded OK")
print(f"    Daemon enabled: {config.get('daemon', {}).get('enabled', False)}")

# 2. Database
print("\n[2] Testing database connection...")
from services.database import PostgreSQLService
try:
    db = PostgreSQLService.get_instance()
    print(f"    DB connected OK")
except Exception as e:
    print(f"    DB connection FAILED: {e}")

# 3. API imports
print("\n[3] Testing API imports...")
try:
    from api import app
    print(f"    API app imported OK")
except Exception as e:
    print(f"    API import FAILED: {e}")

# 4. Daemon imports
print("\n[4] Testing daemon imports...")
try:
    from services.daemon_scheduler import DaemonScheduler
    print(f"    DaemonScheduler imported OK")
except Exception as e:
    print(f"    Daemon import FAILED: {e}")

print("\n" + "=" * 50)
print("Test complete")
print("=" * 50)