from __future__ import annotations

import csv
from pathlib import Path
from typing import List

from ..models import Message

# Canonical column order — matches the schema defined in the proposal
FIELDNAMES = ["session_id", "timestamp", "role", "message", "tool", "file_path"]


class CSVExporter:
    """Writes a list of Messages to a UTF-8 CSV file."""

    def __init__(self, output_path: Path) -> None:
        self.output_path = Path(output_path)

    def export(self, messages: List[Message]) -> int:
        """Write messages to CSV and return the number of rows written."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
            writer.writeheader()
            for msg in messages:
                writer.writerow(msg.to_dict())
        return len(messages)
