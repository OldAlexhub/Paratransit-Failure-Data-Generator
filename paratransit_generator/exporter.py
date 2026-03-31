from __future__ import annotations

from pathlib import Path

import pandas as pd

from .models import GeneratedData


def export_to_csv(data: GeneratedData, directory: str | Path) -> Path:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    for dataset_name, dataframe in data.dataframes.items():
        dataframe.to_csv(target / f"{dataset_name}.csv", index=False)
    return target


def export_to_excel(data: GeneratedData, filepath: str | Path) -> Path:
    target = Path(filepath)
    target.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        for dataset_name, dataframe in data.dataframes.items():
            dataframe.to_excel(writer, sheet_name=dataset_name[:31], index=False)
    return target
