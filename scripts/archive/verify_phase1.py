"""Phase 1 verification: check new model, diagnose data, test predict_proba alignment."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import joblib
import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor
from config import get_config


def verify_model():
    print("=" * 60)
    print("  Model verification")
    print("=" * 60)
    import os
    models_dir = './models/ml/assets'
    pkl_files = sorted(
        [f for f in os.listdir(models_dir) if f.startswith('classifier_v') and f.endswith('.pkl')],
        reverse=True,
    )
    latest = pkl_files[0]
    print(f"  Latest model: {latest}")
    data = joblib.load(os.path.join(models_dir, latest))
    clf = data['model']
    le = data['label_encoder']
    print(f"  Macro F1 (recorded): {data.get('macro_f1', 'N/A')}")
    print(f"  Version           : {data.get('version', 'N/A')}")
    print(f"  Classes (LabelEncoder): {list(le.classes_)}")
    print(f"  Classes (clf)     : {list(clf.classes_)}")
    n_expected = len(le.classes_)
    n_proba = clf.coef_.shape[0]
    print(f"  n_classes in coef : {n_proba}  (expected: {n_expected})")
    if n_proba != n_expected:
        print("  *** WARNING: classes_ mismatch! Will hit IndexError. ***")
    else:
        print("  OK: classes_ aligned with predict_proba columns.")

    # Smoke test: try predict + predict_proba with no searchsorted patching
    print()
    print("  Smoke test: raw predict/predict_proba alignment (no patch)")
    rng = np.random.default_rng(42)
    X = rng.random((5, 1024), dtype=np.float32)
    try:
        preds = clf.predict(X)
        probas = clf.predict_proba(X)
        for i in range(5):
            label_idx = preds[i]
            # WITHOUT the patch (old buggy code path)
            try:
                _ = probas[i][label_idx]
            except IndexError as e:
                print(f"    sample {i}: *** IndexError WITHOUT patch: {e}")
                continue
            # WITH the patch
            proba_col = int(np.searchsorted(clf.classes_, label_idx))
            confidence = float(probas[i][proba_col])
            label = le.inverse_transform([label_idx])[0]
            print(f"    sample {i}: label={label!r}  proba_col={proba_col}  confidence={confidence:.3f}")
    except Exception as e:
        print(f"  *** predict/predict_proba failed: {e}")


def verify_database():
    print()
    print("=" * 60)
    print("  Database verification")
    print("=" * 60)
    cfg = get_config()
    pg = cfg.postgresql
    conn = psycopg2.connect(
        host=pg.host, port=pg.port, user=pg.user,
        password=pg.password, database=pg.database,
        cursor_factory=RealDictCursor,
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""
        SELECT risk_label_level1, COUNT(*) AS cnt
        FROM antiblack.clues
        GROUP BY risk_label_level1
        ORDER BY cnt DESC
    """)
    rows = cur.fetchall()
    print(f"  {'level1':<20} {'count':>10}")
    print("  " + "-" * 32)
    for r in rows:
        print(f"  {r['risk_label_level1']:<20} {r['cnt']:>10}")

    dirty = [r['risk_label_level1'] for r in rows
             if r['risk_label_level1'] not in ('账号交易', '流量作弊', '诈骗引流', '黑产工具', '未知/其他')]
    if dirty:
        print(f"\n  *** WARNING: {len(dirty)} dirty labels still present: {dirty} ***")
    else:
        print("\n  OK: all level1 labels are 5 standard values.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    verify_model()
    verify_database()
