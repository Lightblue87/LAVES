from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent


def _candidate_dataset_roots() -> list[Path]:
    roots: list[Path] = []
    if env_root := os.environ.get("FEEDLABELCHECK_LABEL_TRAINING_ROOT"):
        roots.append(Path(env_root))
    if data_repo := os.environ.get("FEEDLABELCHECK_DATA_REPO"):
        roots.extend([Path(data_repo) / "label_training", Path(data_repo)])
    roots.extend(
        [
            REPO_ROOT.parent / "FeedLabelCheck-Data" / "label_training",
            REPO_ROOT.parent / "FeedLabelCheck-Data",
            REPO_ROOT / "feedlabelcheck_label_training",
        ]
    )
    return roots


def _find_dataset_root() -> Path:
    for root in _candidate_dataset_roots():
        if (root / "ground_truth_starter.json").exists():
            return root
    return REPO_ROOT / "feedlabelcheck_label_training"


DATASET_ROOT = _find_dataset_root()
GROUND_TRUTH = DATASET_ROOT / "ground_truth_starter.json"


pytestmark = pytest.mark.skipif(
    not GROUND_TRUTH.exists(),
    reason="local label training dataset is not present",
)


def _load_dataset() -> dict:
    return json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))


def test_label_training_dataset_references_existing_images() -> None:
    data = _load_dataset()
    referenced = {entry["file"] for entry in data.get("images", [])}
    for product in data.get("products", []):
        referenced.update(product.get("image_files", []))

    assert referenced, "dataset should reference at least one image"
    missing = sorted(
        image for image in referenced if not (DATASET_ROOT / image).is_file()
    )
    assert missing == []


def test_label_training_products_have_required_starter_fields() -> None:
    data = _load_dataset()
    products = data.get("products", [])
    assert products, "dataset should contain product annotations"

    required = {
        "id",
        "product_name",
        "image_files",
        "feed_type",
        "species",
        "expected_fields",
    }
    for product in products:
        missing = sorted(required - set(product))
        assert missing == [], f"{product.get('id', '<unknown>')} missing {missing}"
        assert product["image_files"], f"{product['id']} has no images"
        assert product["feed_type"], f"{product['id']} has no feed_type"
        assert product["species"], f"{product['id']} has no species"


def test_label_training_dataset_reports_unannotated_images() -> None:
    data = _load_dataset()
    referenced = {entry["file"] for entry in data.get("images", [])}
    for product in data.get("products", []):
        referenced.update(product.get("image_files", []))

    image_files = {
        str(path.relative_to(DATASET_ROOT))
        for path in (DATASET_ROOT / "images").iterdir()
        if path.is_file() and path.name != ".DS_Store"
    }
    unannotated = sorted(image_files - referenced)

    # Starter datasets may contain new images before manual annotation. Keep this
    # visible in local test output without treating it as a parser regression.
    if unannotated:
        pytest.xfail(
            f"{len(unannotated)} local training image(s) still need annotation: "
            f"{', '.join(unannotated[:8])}"
        )
