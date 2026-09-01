import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from meridian.config.schema import FirmConfig  # noqa: E402
from meridian.graph.builder import build_graph  # noqa: E402
from meridian.ingestion.csv_ingest import load_holdings  # noqa: E402
from meridian.ingestion.pdf_ingest import parse_guidelines  # noqa: E402

SAMPLE_DOCS = ROOT / "sample_docs"
CONFIGS = ROOT / "configs"


@pytest.fixture(scope="session")
def meridian_graph():
    now = datetime.now(timezone.utc).isoformat()
    guidelines = parse_guidelines(SAMPLE_DOCS / "sample_fund_guidelines.pdf", now)
    positions = load_holdings(SAMPLE_DOCS / "sample_holdings.csv", now)
    return build_graph(guidelines, positions)


@pytest.fixture(scope="session")
def firm_a_config() -> FirmConfig:
    return FirmConfig.load(CONFIGS / "firm_a.yaml")


@pytest.fixture(scope="session")
def firm_b_config() -> FirmConfig:
    return FirmConfig.load(CONFIGS / "firm_b.yaml")
