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
        base = np.random.randn(512).astype(np.float32)
        base /= np.linalg.norm(base)

        vectors = []
        angles = []
        for angle_deg in range(0, 360, 18):
            noise = np.random.randn(512).astype(np.float32)
            noise /= np.linalg.norm(noise)
            frame_vec = base + noise * 0.28
            frame_vec /= np.linalg.norm(frame_vec)
            vectors.append(frame_vec)
            angles.append(f"DEG_{angle_deg}")

        grouped[pid] = {
            "name": name,
            "barcode": barcode,
            "vectors": vectors,
            "angles": angles,
            "source": "SYNTHETIC_SIMULATION"
        }
    return grouped


def fetch_embeddings_from_local_frames() -> Dict[str, Dict]:
    """
    Scans local disk uploads (catalog and scan_frames) for real captured product frames,
    extracts ONNX embeddings, and groups by barcode.
    Used when remote PostgreSQL / Supabase is not reachable locally.
    """
    from PIL import Image
    from app.ai.feature_extractor import get_embeddings_batch
    from app.services.scan_worker import preprocess_product_image_for_embedding

    catalog_dir = backend_dir / "uploads" / "catalog"
    grouped = {}

    if catalog_dir.exists():
        import glob
        cat_files = glob.glob(str(catalog_dir / "*.jpg"))
        for f in cat_files:
            fname = Path(f).name
            parts = fname.split("_")
            if len(parts) >= 2:
                barcode = parts[0]
                angle_tag = parts[1]
                try:
                    img = Image.open(f)
                    preproc = preprocess_product_image_for_embedding(img)
                    if barcode not in grouped:
                        grouped[barcode] = {
                            "name": f"Product-{barcode}",
                            "barcode": barcode,
                            "vectors": [],
                            "angles": [],
                            "source": "REAL_CAPTURED_FRAMES"
                        }
                    vecs = get_embeddings_batch([preproc])
                    if vecs:
                        grouped[barcode]["vectors"].append(vecs[0])
                        grouped[barcode]["angles"].append(angle_tag)
                except Exception:
                    pass

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
        base = np.random.randn(512).astype(np.float32)
        base /= np.linalg.norm(base)

        vectors = []
        angles = []
        for angle_deg in range(0, 360, 18):
            noise = np.random.randn(512).astype(np.float32)
            noise /= np.linalg.norm(noise)
            frame_vec = base + noise * 0.28
            frame_vec /= np.linalg.norm(frame_vec)
            vectors.append(frame_vec)
            angles.append(f"DEG_{angle_deg}")

        grouped[pid] = {
            "name": name,
            "barcode": barcode,
            "vectors": vectors,
            "angles": angles,
            "source": "SYNTHETIC_SIMULATION"
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

    # If DB had fewer than 2 enrolled products, check local disk frames before synthetic
    source_label = "DATABASE"
    if len(grouped_data) < 2:
        try:
            local_frames = fetch_embeddings_from_local_frames()
            if len(local_frames) >= 2:
                grouped_data = local_frames
                source_label = "REAL_CAPTURED_FRAMES"
                print(f"Loaded {len(grouped_data)} products from real local captured catalog frames.")
        except Exception:
            pass

    # If still fewer than 2, fall back to synthetic studio sample
    if len(grouped_data) < 2:
        print("Note: Insufficient enrolled products in active database and local disk.")
        print("Using synthetic studio enrollment simulation (5 products, 20 angles each).")
        grouped_data = generate_synthetic_studio_data()
        is_synthetic = True
        source_label = "SYNTHETIC_SIMULATION"

    print(f"Data source: {source_label} (NOT live cart-camera data)\n")

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

    # 5. Candidate Threshold Analysis (False Accepts vs False Rejects)
    eval_thresholds = [0.60, 0.70, 0.80, 0.85]
    total_intra = len(intra_sims)
    total_inter = len(inter_sims)

    print("\n--- Empirical Decision Analysis Across Candidate Thresholds ---")
    print(f"{'Threshold':<10} | {'False Accepts (Diff Item >= Thresh)':<40} | {'False Rejects (Same Item < Thresh)':<36}")
    print("-" * 92)
    for t in eval_thresholds:
        fa = sum(1 for s in inter_sims if s >= t)
        fa_rate = (fa / total_inter * 100.0) if total_inter > 0 else 0.0
        fr = sum(1 for s in intra_sims if s < t)
        fr_rate = (fr / total_intra * 100.0) if total_intra > 0 else 0.0
        print(f"{t:<10.2f} | {fa:<5} ({fa_rate:5.1f}%)                              | {fr:<5} ({fr_rate:5.1f}%)")

    # 6. Threshold Explanation & Advisory
    # CONFIDENCE_HIGH: Auto-approve threshold. Score >= HIGH and gap >= 0.05.
    # CONFIDENCE_LOW: Minimum plausible match threshold.
    suggested_high = max(0.75, round(float(intra_stats["p5"]), 2))
    suggested_low = min(suggested_high - 0.10, max(0.55, round(float(inter_stats["p95"]) + 0.05, 2)))

    print("\n--- Threshold Explanation & Live Calibration Advisory ---")
    print("  • CONFIDENCE_HIGH: Auto-approves placement as VERIFIED without human review.")
    print("    - Higher HIGH reduces False Accepts (mistaking wrong item for claimed item), but increases False Rejects.")
    print("    - NOTE: Do NOT treat 0.85 as a rigid final threshold! On real multi-angle frames, true matches may score 0.72-0.84.")
    print("  • CONFIDENCE_LOW : Minimum threshold for considering a visual candidate.")
    print("    - Between LOW and HIGH: triggers 'Please reposition item or show label'.")
    print("    - Below LOW: escalates to Admin Review Queue / Staff Alert.")
    print(f"  • Suggested Starting (from this dataset): HIGH={suggested_high:.2f}, LOW={suggested_low:.2f}")

    print("\n" + "!" * 78)
    print("CRITICAL DEPLOYMENT ADVISORY:")
    if is_synthetic:
        print("These threshold calculations were derived from SYNTHETIC simulation (5 orthogonal centroids).")
    else:
        print(f"These threshold calculations were derived from {source_label}.")
    print("Studio / synthetic frames do not reflect live overhead cart camera conditions.")
    print("Use the 'Live Calibration Session' on /cart-device or Admin to collect 10-20 live frames")
    print("and set CONFIDENCE_HIGH and CONFIDENCE_LOW from empirical live camera data.")
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
