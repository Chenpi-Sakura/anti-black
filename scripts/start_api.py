"""
AntiBlack API Server Entry Point
"""
import uvicorn
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import get_config
from api import app

def main():
    config = get_config()
    port = config.get('api', {}).get('port', 8000)
    host = config.get('api', {}).get('host', '0.0.0.0')
    
    print(f"Starting AntiBlack API server on {host}:{port}...")
    uvicorn.run("api:app", host=host, port=port, log_level="info", reload=False)

if __name__ == "__main__":
    main()
