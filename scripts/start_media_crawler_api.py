import os
import sys
import uvicorn
from pathlib import Path

# Load .env file so postgres env vars are available to subprocesses
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

sys.path.insert(0, str(Path(__file__).parent.parent / 'MediaCrawler'))
from api.main import app

if __name__ == '__main__':
    print('Starting MediaCrawler API server on port 8092...')
    print(f'POSTGRES_DB_HOST={os.getenv("POSTGRES_DB_HOST")}')
    uvicorn.run(app, host='127.0.0.1', port=8092, log_level='info')
