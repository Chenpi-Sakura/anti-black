"""
Manually trigger embedding classifier retraining.
Usage: conda run -n anti-black python scripts/trigger_retrain.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_config
from services.model_retrainer import ModelRetrainer, extend_postgres_service


async def main():
    extend_postgres_service()
    cfg = get_config()
    cfg_dict = {
        'auto_evolution': cfg.auto_evolution.__dict__ if hasattr(cfg.auto_evolution, '__dict__') else cfg.auto_evolution,
    }
    r = ModelRetrainer(config=cfg_dict)
    await r.initialize()
    print("=== Pre-check: silver/platinum sample counts ===")
    silver = r._db.count_silver_samples()
    platinum = r._db.count_platinum_samples()
    print(f"  silver  : {silver}")
    print(f"  platinum: {platinum}")
    print(f"  total   : {silver + platinum}  (threshold: 2000)")
    print()
    print("=== Running retrain ===")
    await r._run_retrain()
    print()
    print("=== Done. Check the latest classifier_v*.pkl in models/ml/assets/ ===")


if __name__ == "__main__":
    asyncio.run(main())
