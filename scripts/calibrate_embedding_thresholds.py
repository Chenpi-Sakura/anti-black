"""Calibrate embedding reject thresholds using histogram-driven analysis.

Strategy:
  1. Take positive (黑产) samples and negative (无关) samples.
  2. For each, compute the embedding classifier's predict_proba output
     (max_proba and top1-top2 margin).
  3. Histogram both distributions; pick reject/margin thresholds that
     maximize TPR (黑产保留率) at fixed FPR (无关误判率 < 5%).

Usage:
    python scripts/calibrate_embedding_thresholds.py --n 2000
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import os
import joblib
import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor
import httpx
from config import get_config


OLLAMA_API_URL = "http://localhost:11434/api/embed"
EMBEDDING_MODEL = "bge-m3"


def load_samples(conn, n_pos: int, n_neg: int):
    cur = conn.cursor()
    # Positive: black-market samples (not 未知/其他, not 无关) with confidence >= 0.8
    cur.execute("""
        SELECT clue_id, cleaned_text
        FROM antiblack.clues
        WHERE risk_label_level1 IN ('账号交易', '流量作弊', '诈骗引流', '黑产工具')
          AND confidence >= 0.8
          AND LENGTH(cleaned_text) BETWEEN 8 AND 500
        ORDER BY RANDOM()
        LIMIT %s
    """, (n_pos,))
    pos = cur.fetchall()

    # Negative: irrelevant_samples
    cur.execute("""
        SELECT sample_id AS clue_id, cleaned_text
        FROM antiblack.irrelevant_samples
        ORDER BY RANDOM()
        LIMIT %s
    """, (n_neg,))
    neg = cur.fetchall()
    return pos, neg


def batch_embed(texts, batch_size=32):
    """Call Ollama embed API in batches."""
    all_embs = []
    with httpx.Client(timeout=60.0) as client:
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                r = client.post(OLLAMA_API_URL, json={"model": EMBEDDING_MODEL, "input": batch})
                r.raise_for_status()
                embs = r.json().get('embeddings', [])
                all_embs.extend(embs)
            except Exception as e:
                print(f"  embed batch {i} failed: {e}")
                all_embs.extend([[0.0] * 1024 for _ in batch])
    return np.array(all_embs, dtype=np.float32)


def histogram(values, n_bins=10):
    """Return a list of (bin_center, count) tuples for the value distribution."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [(lo, len(values))]
    bin_w = (hi - lo) / n_bins
    counts = [0] * n_bins
    for v in values:
        idx = min(int((v - lo) / bin_w), n_bins - 1)
        counts[idx] += 1
    return [(lo + bin_w * (i + 0.5), counts[i]) for i in range(n_bins)]


def find_threshold(values, fpr_target=0.05):
    """Find value threshold that keeps fpr_target fraction of values above it.
    For negative samples: fpr is the fraction *above* the threshold.
    """
    if not values:
        return None
    sorted_v = sorted(values, reverse=True)
    # Number of negative samples to allow ABOVE the threshold
    n_allowed = max(1, int(len(sorted_v) * fpr_target))
    return sorted_v[n_allowed - 1]


def main():
    parser = argparse.ArgumentParser(description='Calibrate embedding reject thresholds')
    parser.add_argument('--n', type=int, default=2000, help='Samples per class')
    parser.add_argument('--fpr', type=float, default=0.05, help='Target FPR for threshold search')
    parser.add_argument('--dryrun', action='store_true', help='Skip Ollama call (use precomputed)')
    args = parser.parse_args()

    cfg = get_config()
    pg = cfg.postgresql
    conn = psycopg2.connect(
        host=pg.host, port=pg.port, user=pg.user,
        password=pg.password, database=pg.database,
        cursor_factory=RealDictCursor,
    )
    conn.autocommit = True

    print(f"[load] {args.n} positive + {args.n} negative samples")
    pos, neg = load_samples(conn, args.n, args.n)
    print(f"  pos: {len(pos)}, neg: {len(neg)}")

    if not pos or not neg:
        print("Insufficient samples. Run collect_irrelevant_samples.py first.")
        return

    # Load embedding classifier
    models_dir = './models/ml/assets'
    pkl_files = sorted(
        [f for f in os.listdir(models_dir) if f.startswith('classifier_v') and f.endswith('.pkl')],
        reverse=True,
    )
    if not pkl_files:
        print(f"No classifier found in {models_dir}")
        return
    latest = pkl_files[0]
    print(f"[model] {latest}")
    data = joblib.load(os.path.join(models_dir, latest))
    clf = data['model']
    le = data['label_encoder']
    print(f"  classes: {list(le.classes_)}")

    # Embed and predict
    if args.dryrun:
        print("Dryrun: skipping embedding call")
        return

    print(f"[embed] calling Ollama for {len(pos) + len(neg)} texts...")
    all_texts = [r['cleaned_text'] for r in pos] + [r['cleaned_text'] for r in neg]
    X = batch_embed(all_texts)
    print(f"  embeddings: {X.shape}")

    probas = clf.predict_proba(X)

    pos_max = []
    pos_margin = []
    for i in range(len(pos)):
        p = probas[i]
        pos_max.append(float(p.max()))
        sorted_p = np.sort(p)
        pos_margin.append(float(p.max() - sorted_p[-2]))

    neg_max = []
    neg_margin = []
    for i in range(len(neg)):
        p = probas[len(pos) + i]
        neg_max.append(float(p.max()))
        sorted_p = np.sort(p)
        neg_margin.append(float(p.max() - sorted_p[-2]))

    # Histograms
    out = Path(__file__).parent / "_threshold_calibration.txt"
    with open(out, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("  Threshold calibration report\n")
        f.write("=" * 60 + "\n\n")

        f.write(f"Pos samples (黑产): {len(pos)}\n")
        f.write(f"Neg samples (无关): {len(neg)}\n\n")

        f.write("== max_proba distribution ==\n")
        f.write("bin_center | pos_count | neg_count\n")
        f.write("-" * 40 + "\n")
        bins_pos = histogram(pos_max, 10)
        bins_neg = histogram(neg_max, 10)
        for (bp, cp), (bn, cn) in zip(bins_pos, bins_neg):
            f.write(f"  {bp:6.3f}   | {cp:9d} | {cn:9d}\n")

        f.write("\n== margin (top1-top2) distribution ==\n")
        f.write("bin_center | pos_count | neg_count\n")
        f.write("-" * 40 + "\n")
        bins_pos = histogram(pos_margin, 10)
        bins_neg = histogram(neg_margin, 10)
        for (bp, cp), (bn, cn) in zip(bins_pos, bins_neg):
            f.write(f"  {bp:6.3f}   | {cp:9d} | {cn:9d}\n")

        # Suggest thresholds
        max_thresh = find_threshold(neg_max, args.fpr)
        margin_thresh = find_threshold(neg_margin, args.fpr)

        f.write(f"\n== Suggested thresholds (FPR ≤ {args.fpr:.0%}) ==\n")
        f.write(f"  embedding_reject_threshold: {max_thresh:.3f}  (current default: 0.45)\n")
        f.write(f"  embedding_margin_threshold: {margin_thresh:.3f}  (current default: 0.12)\n")
        if max_thresh is not None:
            tpr_at_max = sum(1 for v in pos_max if v >= max_thresh) / max(len(pos_max), 1)
            fpr_at_max = sum(1 for v in neg_max if v >= max_thresh) / max(len(neg_max), 1)
            f.write(f"    At max_proba ≥ {max_thresh:.3f}: TPR={tpr_at_max:.2%}, FPR={fpr_at_max:.2%}\n")
        if margin_thresh is not None:
            tpr_at_mar = sum(1 for v in pos_margin if v >= margin_thresh) / max(len(pos_margin), 1)
            fpr_at_mar = sum(1 for v in neg_margin if v >= margin_thresh) / max(len(neg_margin), 1)
            f.write(f"    At margin ≥ {margin_thresh:.3f}: TPR={tpr_at_mar:.2%}, FPR={fpr_at_mar:.2%}\n")

        f.write("\n== How to apply ==\n")
        f.write("Edit config.yaml:\n")
        f.write("  classification:\n")
        if max_thresh is not None:
            f.write(f"    embedding_reject_threshold: {max_thresh:.3f}\n")
        if margin_thresh is not None:
            f.write(f"    embedding_margin_threshold: {margin_thresh:.3f}\n")

    print(f"\n[done] report written to {out.name}")
    print("Use --fpr 0.02 for stricter, --fpr 0.10 for more lenient thresholds.")
    conn.close()


if __name__ == "__main__":
    main()
