"""Smoke test: run UnknownDiscovery end-to-end on whatever '未知/其他' samples we have.

Temporarily relaxes thresholds to make the demo runnable on small data.
Real production runs use config.yaml values (min_cluster_size=30 etc.).
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

from config import get_config
from pipeline.unknown_discovery import UnknownDiscovery


async def main():
    cfg = get_config()
    out_path = Path(__file__).parent / "_discovery_smoketest_output.txt"
    out_f = open(out_path, 'w', encoding='utf-8')

    def emit(s=""):
        print(s)
        out_f.write(s + "\n")
        out_f.flush()

    # Build the discovery instance with relaxed thresholds for the demo
    test_config = {
        'unknown_discovery': {
            'umap_n_components': 10,
            'umap_n_neighbors': 10,    # smaller for limited data
            'umap_min_dist': 0.0,
            'umap_metric': 'cosine',
            'umap_random_state': 42,
            'min_cluster_size': 8,     # relaxed
            'min_samples': 3,
            'hdbscan_metric': 'euclidean',
            'min_cluster_size_for_proposal': 8,  # relaxed
            'min_appearance_days': 1,
            'top_k_samples_per_cluster': 5,
            'cosine_dedup_threshold': 0.85,
            'min_level2_chars': 2,
            'max_level2_chars': 6,
            'min_llm_confidence': 0.7,  # slightly relaxed
        }
    }
    ud = UnknownDiscovery(config=test_config)

    print("=" * 60)
    print("  Step 1: Fetching 未知/其他 samples")
    print("=" * 60)
    samples = ud.fetch_unknown_samples(lookback_days=30)
    print(f"  Fetched: {len(samples)} samples")
    if len(samples) < 10:
        print("  Too few samples to do anything meaningful. Aborting.")
        return

    print()
    print("=" * 60)
    print("  Step 2: Embedding via Ollama bge-m3")
    print("=" * 60)
    texts = [s['cleaned_text'] for s in samples]
    X = ud.embed_texts(texts)
    print(f"  X shape: {X.shape}")

    print()
    print("=" * 60)
    print("  Step 3: UMAP reduction to 10D")
    print("=" * 60)
    X_low, _ = ud.reduce_umap(X, fit=True)
    print(f"  X_low shape: {X_low.shape}")

    print()
    print("=" * 60)
    print("  Step 4: HDBSCAN clustering")
    print("=" * 60)
    cluster_labels, _ = ud.cluster_hdbscan(X_low)
    unique, counts = np.unique(cluster_labels, return_counts=True)
    print(f"  Found {len(unique) - (1 if -1 in unique else 0)} clusters (+ noise)")
    for u, c in zip(unique, counts):
        tag = "noise" if u == -1 else f"cluster"
        print(f"    {tag} {u}: {c} samples")

    print()
    print("=" * 60)
    print("  Step 5: For each cluster, centroid sample + LLM naming")
    print("=" * 60)
    accepted = []
    for cid in unique:
        if cid == -1:
            continue
        cluster_idx = np.where(cluster_labels == cid)[0]
        if len(cluster_idx) < ud.min_cluster_size_for_proposal:
            print(f"  cluster {cid}: skip (size {len(cluster_idx)} < {ud.min_cluster_size_for_proposal})")
            continue
        sample_texts = ud.centroid_sample(X_low, cluster_idx, texts, ud.top_k)
        print(f"  cluster {cid} (size={len(cluster_idx)}): top {len(sample_texts)} centroid samples")
        for i, t in enumerate(sample_texts):
            print(f"    {i+1}. {t[:80]}")

        cluster_mean = X[cluster_idx].mean(axis=0)
        llm_resp = await ud.name_cluster_with_llm(sample_texts, len(cluster_idx))
        if llm_resp is None:
            print(f"    LLM: no response, skip")
            continue
        print(f"    LLM raw: {llm_resp}")

        ok, reason = ud.code_level_assertions(llm_resp)
        print(f"    assertions: ok={ok}, reason={reason}")
        if not ok:
            continue

        is_dup, similar = ud.is_duplicate_of_existing(
            llm_resp.get("proposed_level1", ""),
            llm_resp.get("proposed_level2", ""),
        )
        print(f"    dedup_vs_taxonomy: is_dup={is_dup}, similar={similar!r}")
        if is_dup:
            continue

        pool_dup = ud.find_duplicate_in_pool(llm_resp.get("proposed_level2", ""))
        print(f"    dedup_vs_pool: hit={pool_dup is not None}")
        if pool_dup:
            continue

        # Don't actually write to DB for the demo unless --commit is passed
        accepted.append({
            "cluster_id": str(cid),
            "size": len(cluster_idx),
            "level1": llm_resp.get("proposed_level1"),
            "level2": llm_resp.get("proposed_level2"),
            "confidence": llm_resp.get("confidence"),
            "chain_of_thought": llm_resp.get("chain_of_thought"),
            "cluster_mean": cluster_mean,
            "sample_texts": sample_texts,
            "llm_resp": llm_resp,
        })

    print()
    print("=" * 60)
    print(f"  Step 6: Summary — {len(accepted)} proposals ready")
    print("=" * 60)
    for a in accepted:
        print(f"  - cluster {a['cluster_id']} (n={a['size']}): {a['level1']}/{a['level2']} (conf={a['confidence']})")
        print(f"      reason: {a['chain_of_thought']}")

    if accepted and "--commit" in sys.argv:
        print("\n[commit] Writing proposals to DB...")
        for a in accepted:
            pid = ud.write_proposal(
                cluster_id=a['cluster_id'],
                cluster_size=a['size'],
                sample_texts=a['sample_texts'],
                cluster_mean_emb=a['cluster_mean'],
                llm_resp=a['llm_resp'],
            )
            print(f"  wrote: {pid}")
    elif accepted:
        print("\n[dryrun] No proposals written. Pass --commit to write them to DB.")

    out_f.close()
    print(f"\n[log] Full output also written to {out_path.name}")


if __name__ == "__main__":
    asyncio.run(main())
