from pathlib import Path


REQUIRED_DATASETS = [
    "XAU_1m_data.csv",
    "XAU_5m_data.csv",
    "XAU_15m_data.csv",
    "XAU_30m_data.csv",
    "XAU_1h_data.csv",
    "XAU_4h_data.csv",
    "XAU_1d_data.csv",
    "XAU_1w_data.csv",
    "XAU_1Month_data.csv",
]


def validate_required_datasets(data_dir: str = "data") -> tuple[list[str], list[str]]:
    path = Path(data_dir)

    present: list[str] = []
    missing: list[str] = []

    for name in REQUIRED_DATASETS:
        if (path / name).exists():
            present.append(name)
        else:
            missing.append(name)

    return present, missing