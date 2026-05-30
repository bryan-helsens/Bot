"""Optional machine-learning module.

Generates *signals only*; every AI signal is validated by the risk engine before
any order is placed. Heavy ML libraries (scikit-learn, XGBoost, LightGBM, PyTorch)
are optional and imported lazily, so the core bot runs without them. Install with
``pip install 'quantbot[ai]'``.
"""

from __future__ import annotations
