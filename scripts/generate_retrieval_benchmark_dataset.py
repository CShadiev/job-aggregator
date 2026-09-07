"""Generate or export the gating retrieval benchmark dataset.

Repurposes screening dataset entries with precomputed 1536-d embeddings
and single candidate query profile.
"""

from __future__ import annotations

from scripts.generate_gating_benchmark_dataset import main

if __name__ == "__main__":
    main()
