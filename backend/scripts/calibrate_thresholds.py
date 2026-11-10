"""
Model Threshold Calibration Script
===================================
Analyzes cosine similarity distributions across stored enrollment frames
for enrolled products in the smart cart catalog.

Measures:
  1. Intra-product cosine similarity (same product, different camera angles)
  2. Inter-product cosine similarity (different products)

Outputs:
  - Distribution metrics: min, mean, max, p5, p50, p95
  - ASCII histogram comparing intra vs inter product similarity
  - Suggested starting values for CONFIDENCE_HIGH and CONFIDENCE_LOW
  - Explicit advisory regarding studio vs live cart-camera conditions.
"""

import sys
import os
import json
import argparse
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal, engine
from app.models.product import Product, ProductEmbedding, ProductImage


def compute_cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """Computes cosine similarity between two 1D normalized or unnormalized vectors."""
    n1 = np.linalg.norm(vec1)
    n2 = np.linalg.norm(vec2)
    if n1 == 0 or n2 == 0:
        return 0.0
    return float(np.dot(vec1, vec2) / (n1 * n2))


def fetch_embeddings_by_product(db) -> Dict[str, Dict]:
    """
    Fetches all product embeddings grouped by product.
    Returns:
        dict: product_id -> {
            "name": str,
            "barcode": str,
            "vectors": List[np.ndarray],
            "angles": List[str]
        }
    """
    records = db.query(ProductEmbedding).all()
    grouped = {}
    for r in records:
        if not r.embedding_json:
            continue
        try:
            vec = np.array(json.loads(r.embedding_json), dtype=np.float32)
            if vec.ndim != 1 or len(vec) == 0:
                continue
            # Normalize vector
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
        except Exception:
            continue

        pid = r.product_id
        if pid not in grouped:
            prod_name = r.product.name if r.product else f"Product-{pid[:6]}"
            grouped[pid] = {
                "name": prod_name,
                "barcode": r.barcode,
                "vectors": [],
                "angles": []
            }
        grouped[pid]["vectors"].append(vec)
        grouped[pid]["angles"].append(r.angle_tag)

    return grouped


def generate_synthetic_studio_data() -> Dict[str, Dict]:
    """
    Generates synthetic studio embeddings simulating a 360 enrollment session
    for benchmarking when the target database has no or few enrolled items.
    """
    np.random.seed(42)
    classes = [
        ("Amul Butter 500g", "890126201001"),
        ("Tata Tea Gold 250g", "890126201002"),
        ("Britannia Good Day 100g", "890126201003"),
        ("Maggi 2-Minute Noodles", "890126201004"),
        ("Parle-G Gold Biscuits", "890126201005")
    ]
    grouped = {}
    for idx, (name, barcode) in enumerate(classes):
        pid = f"synthetic-{idx+1}"
        # Base vector on 512-dimensional sphere
        base = np.random.randn(512).astype(np.float32)
        base /= np.linalg.norm(base)

        vectors = []
        angles = []
        # Generate 20 multi-angle frames around this product with high intra-class correlation
        for angle_deg in range(0, 360, 18):
            # Controlled perturbation representing multi-angle studio capture (intra cosine ~0.84 to 0.96)
            noise = np.random.randn(512).astype(np.float32)
            noise /= np.linalg.norm(noise)
            # Add small angular offset per viewpoint (0.28 norm perturbation)
            frame_vec = base + noise * 0.28
            frame_vec /= np.linalg.norm(frame_vec)
            vectors.append(frame_vec)
            angles.append(f"DEG_{angle_deg}")

        grouped[pid] = {
            "name": name,
            "barcode": barcode,
            "vectors": vectors,
            "angles": angles
        }
    return grouped


def calculate_distribution_stats(values: List[float]) -> Dict[str, float]:
    """Computes min, mean, max, p5, p50, p95 for a list of floats."""
    if not values:
        return {"min": 0.0, "mean": 0.0, "max": 0.0, "p5": 0.0, "p50": 0.0, "p95": 0.0, "count": 0}
    arr = np.array(values)
    return {
        "min": float(np.min(arr)),
        "mean": float(np.mean(arr)),
        "max": float(np.max(arr)),
        "p5": float(np.percentile(arr, 5)),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "count": len(arr)
    }


def print_histogram(intra_sims: List[float], inter_sims: List[float]):
    """Renders a comparative ASCII histogram between intra-product and inter-product similarity."""
    bins = [
        (0.00, 0.40, "< 0.40"),
        (0.40, 0.50, "0.40 - 0.50"),
        (0.50, 0.60, "0.50 - 0.60"),
        (0.60, 0.70, "0.60 - 0.70"),
        (0.70, 0.75, "0.70 - 0.75"),
        (0.75, 0.80, "0.75 - 0.80"),
        (0.80, 0.85, "0.80 - 0.85"),
        (0.85, 0.90, "0.85 - 0.90"),
        (0.90, 0.95, "0.90 - 0.95"),
        (0.95, 1.00, "0.95 - 1.00"),
    ]

    intra_arr = np.array(intra_sims) if intra_sims else np.array([])
    inter_arr = np.array(inter_sims) if inter_sims else np.array([])

    total_intra = len(intra_arr)
    total_inter = len(inter_arr)

    print("\n" + "=" * 78)
    print(f"{'SIMILARITY BIN':<16} | {'INTRA-PRODUCT (Same)':<26} | {'INTER-PRODUCT (Diff)':<26}")
    print("=" * 78)

    for low, high, label in bins:
        if high == 1.00:
            c_intra = np.sum((intra_arr >= low) & (intra_arr <= high)) if total_intra > 0 else 0
            c_inter = np.sum((inter_arr >= low) & (inter_arr <= high)) if total_inter > 0 else 0
        else:
            c_intra = np.sum((intra_arr >= low) & (intra_arr < high)) if total_intra > 0 else 0
            c_inter = np.sum((inter_arr >= low) & (inter_arr < high)) if total_inter > 0 else 0

        pct_intra = (c_intra / total_intra * 100) if total_intra > 0 else 0.0
        pct_inter = (c_inter / total_inter * 100) if total_inter > 0 else 0.0

        bar_intra = "█" * int(pct_intra / 5)
        bar_inter = "░" * int(pct_inter / 5)

        intra_str = f"{pct_intra:5.1f}% ({c_intra:<4}) {bar_intra}"
        inter_str = f"{pct_inter:5.1f}% ({c_inter:<4}) {bar_inter}"

        print(f"{label:<16} | {intra_str:<26} | {inter_str:<26}")
    print("=" * 78)


def run_calibration(db_session=None, use_synthetic: bool = False):
    print("=" * 78)
    print("SMART CART AI EMBEDDING CALIBRATION REPORT")
    print("=" * 78)

    grouped_data = {}
    is_synthetic = False

    if not use_synthetic and db_session is not None:
        try:
            grouped_data = fetch_embeddings_by_product(db_session)
            print(f"Loaded {len(grouped_data)} products with embeddings from database.")
        except Exception as e:
            print(f"Warning: Could not fetch embeddings from database ({e}).")

    # If DB had fewer than 2 enrolled products, fall back to synthetic studio sample
    if len(grouped_data) < 2:
        print("Note: Insufficient enrolled products in active database (minimum 2 required).")
        print("Using synthetic studio enrollment simulation (5 products, 20 angles each).")
        grouped_data = generate_synthetic_studio_data()
        is_synthetic = True

    # 1. Compute intra-product similarities (same product, different angles)
    intra_sims: List[float] = []
    per_product_stats = {}

    for pid, pdata in grouped_data.items():
        vectors = pdata["vectors"]
        p_sims = []
        n_vec = len(vectors)
        if n_vec >= 2:
            for i in range(n_vec):
                for j in range(i + 1, n_vec):
                    sim = compute_cosine_similarity(vectors[i], vectors[j])
                    intra_sims.append(sim)
                    p_sims.append(sim)
            per_product_stats[pdata["name"]] = calculate_distribution_stats(p_sims)

    # 2. Compute inter-product similarities (different products)
    inter_sims: List[float] = []
    pids = list(grouped_data.keys())
    for idx_a in range(len(pids)):
        for idx_b in range(idx_a + 1, len(pids)):
            vecs_a = grouped_data[pids[idx_a]]["vectors"]
            vecs_b = grouped_data[pids[idx_b]]["vectors"]
            # Subsample up to 20 vectors per class to avoid $O(N^2)$ blowout
            sub_a = vecs_a[:20]
            sub_b = vecs_b[:20]
            for va in sub_a:
                for vb in sub_b:
                    sim = compute_cosine_similarity(va, vb)
                    inter_sims.append(sim)

    # 3. Compute overall distribution metrics
    intra_stats = calculate_distribution_stats(intra_sims)
    inter_stats = calculate_distribution_stats(inter_sims)

    print("\n--- Summary Statistics (Cosine Similarity) ---")
    print(f"{'Metric':<12} | {'Intra-Product (Same)':<22} | {'Inter-Product (Different)':<25}")
    print("-" * 65)
    for m in ["count", "min", "p5", "p50", "mean", "p95", "max"]:
        val_intra = f"{intra_stats[m]:.4f}" if m != "count" else f"{int(intra_stats[m])}"
        val_inter = f"{inter_stats[m]:.4f}" if m != "count" else f"{int(inter_stats[m])}"
        print(f"{m.upper():<12} | {val_intra:<22} | {val_inter:<25}")

    # 4. Print comparative ASCII histogram
    print_histogram(intra_sims, inter_sims)

    # 5. Threshold Suggestion Logic
    # CONFIDENCE_HIGH: set near intra-product p5, provided it is well above inter-product p95
    suggested_high = max(0.85, round(float(intra_stats["p5"]), 2))
    # CONFIDENCE_LOW: set slightly above inter-product p95 to filter random mismatches
    suggested_low = min(suggested_high - 0.10, max(0.68, round(float(inter_stats["p95"]) + 0.05, 2)))

    print("\n--- Recommended Starting Thresholds ---")
    print(f"  • CONFIDENCE_HIGH: {suggested_high:.2f} (Auto-approve placement when top match >= HIGH and gap >= 0.05)")
    print(f"  • CONFIDENCE_LOW : {suggested_low:.2f} (Ask shopper to reposition / flag wrong item when between LOW & HIGH)")
    print(f"  • Below {suggested_low:.2f}   : Route to Admin Review Queue / Staff Alert")

    print("\n" + "!" * 78)
    print("CRITICAL DEPLOYMENT ADVISORY:")
    if is_synthetic:
        print("These threshold calculations were derived from synthetic studio enrollment vectors.")
    else:
        print("These threshold calculations were derived from studio 360° enrollment frames.")
    print("Studio frames have controlled ring lighting, turntable rotation, and uniform backdrops.")
    print("Real cart overhead camera frames will exhibit:")
    print("  1. Customer hand shadows and basket grid occlusion")
    print("  2. Store ambient lighting variations and glare")
    print("  3. Non-perpendicular viewing angles")
    print("Empirical in-situ tuning on live cart frames is strictly required before locking thresholds.")
    print("!" * 78 + "\n")

    return {
        "intra_stats": intra_stats,
        "inter_stats": inter_stats,
        "suggested_high": suggested_high,
        "suggested_low": suggested_low,
        "is_synthetic": is_synthetic
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calibrate SmartCart visual verification thresholds.")
    parser.add_argument("--synthetic", action="store_true", help="Force synthetic studio benchmark evaluation")
    args = parser.parse_args()

    session = None
    if not args.synthetic and SessionLocal is not None:
        try:
            session = SessionLocal()
        except Exception:
            session = None

    try:
        run_calibration(db_session=session, use_synthetic=args.synthetic)
    finally:
        if session is not None:
            session.close()
