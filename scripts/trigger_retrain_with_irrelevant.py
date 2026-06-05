"""Retrain the embedding classifier with IRRELEVANT negative samples.

Loads:
  - silver samples (high-confidence clues, confidence >= 0.8, no feedback)
  - negative samples from antiblack.irrelevant_samples (label = '无关')
  - platinum samples (manually verified feedback) — usually empty
  - error book samples — usually empty

Combines into a 6-class training set:
  账号交易, 流量作弊, 诈骗引流, 黑产工具, 未知/其他, 无关

Negatives get weight 0.3 (lower) to avoid dominating the 5 real classes.

Usage: conda run -n anti-black python scripts/trigger_retrain_with_irrelevant.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import joblib
import numpy as np
import psycopg2
import psycopg2.extras
from config import get_config

from pipeline.classifier import Classifier
from services.model_retrainer import extend_postgres_service


def fetch_training_data(neg_weight: float = 0.3):
    cfg = get_config()
    pg = cfg.postgresql
    conn = psycopg2.connect(
        host=pg.host, port=pg.port, user=pg.user,
        password=pg.password, database=pg.database,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = True
    cur = conn.cursor()

    # Silver samples (high-confidence, no feedback)
    cur.execute("""
        SELECT c.cleaned_text AS text, c.risk_label_level1 AS label
        FROM antiblack.clues c
        LEFT JOIN antiblack.feedback f ON c.clue_id = f.clue_id
        WHERE c.confidence >= 0.8
          AND f.feedback_id IS NULL
          AND c.risk_label_level1 IN ('账号交易', '流量作弊', '诈骗引流', '黑产工具', '未知/其他')
          AND LENGTH(c.cleaned_text) BETWEEN 8 AND 500
        ORDER BY RANDOM()
    """)
    silver = cur.fetchall()
    print(f"  silver  : {len(silver)}")

    # Irrelevant (negative) samples
    cur.execute("""
        SELECT cleaned_text AS text, '无关' AS label
        FROM antiblack.irrelevant_samples
        WHERE LENGTH(cleaned_text) BETWEEN 8 AND 500
    """)
    neg = cur.fetchall()
    print(f"  neg     : {len(neg)}")

    cur.close()
    conn.close()

    texts = []
    labels = []
    weights = []
    for r in silver:
        if r['text']:
            texts.append(r['text'])
            labels.append(r['label'])
            weights.append(1.0)
    for r in neg:
        if r['text']:
            texts.append(r['text'])
            labels.append(r['label'])
            weights.append(neg_weight)

    return {'texts': texts, 'labels': labels, 'weights': weights}


async def main():
    print("=== Building 6-class training set (5 + IRRELEVANT) ===")
    train_data = fetch_training_data()
    n_pos = sum(1 for w in train_data['weights'] if w >= 1.0)
    n_neg = sum(1 for w in train_data['weights'] if w < 1.0)
    print(f"  pos (5 real classes): {n_pos}")
    print(f"  neg (IRRELEVANT)    : {n_neg}")
    print(f"  total                : {len(train_data['texts'])}")

    if n_neg == 0:
        print("[abort] No negative samples. Run scripts/collect_irrelevant_samples.py first.")
        return

    print()
    print("=== Training (this may take a few minutes) ===")
    classifier = Classifier()
    new_version = await classifier.retrain(train_data)

    if new_version:
        # Inspect the new model
        model_path = f"./models/ml/assets/classifier_v{new_version}.pkl"
        data = joblib.load(model_path)
        clf = data['model']
        le = data['label_encoder']
        print()
        print("=== New model summary ===")
        print(f"  Macro F1: {data.get('macro_f1', 'N/A'):.4f}")
        print(f"  Classes (LabelEncoder): {[str(c) for c in le.classes_]}")
        print(f"  Classes (clf)         : {list(clf.classes_)}")
        print(f"  n_classes in coef     : {clf.coef_.shape[0]}")
        if clf.coef_.shape[0] == len(le.classes_):
            print("  OK: classes_ aligned with predict_proba columns")
        else:
            print("  *** WARNING: classes_ mismatch! Will hit IndexError.")
    else:
        print("[failed] retrain returned None")


if __name__ == "__main__":
    asyncio.run(main())
