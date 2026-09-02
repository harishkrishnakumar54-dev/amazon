import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("amazon_scraper")

DEFAULT_PROGRESS_PATH = "output/progress.json"

class ProgressTracker:
    """
    Manages persistent state in output/progress.json to ensure
    resumability across scraper runs and workflow timeouts.
    """
    def __init__(self, progress_path: str = DEFAULT_PROGRESS_PATH):
        self.progress_path = Path(progress_path).resolve()
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self.state: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        default_state = {
            "completed_categories": [],
            "failed_categories": [],
            "current_category": "",
            "last_completed_category": "",
            "last_checkpoint_timestamp": None,
            "excel_row_count": 0,
            "database_record_count": 0
        }
        if not self.progress_path.exists():
            return default_state

        try:
            with open(self.progress_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Merge with default structure to prevent missing keys
                    default_state.update(data)
                    return default_state
        except Exception as e:
            logger.warning(f"Could not load existing progress from {self.progress_path}: {e}")

        return default_state

    def save(self) -> None:
        temp_path = self.progress_path.with_suffix(".json.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
            os.replace(str(temp_path), str(self.progress_path))
        except Exception as e:
            logger.error(f"Failed to atomically write progress file: {e}")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    def start_category(self, category: str) -> None:
        self.state["current_category"] = category
        self.save()

    def mark_completed(
        self,
        category: str,
        excel_row_count: int,
        database_record_count: int
    ) -> None:
        """
        Marks category as completed AFTER SQLite save, Excel save,
        and Excel validation have all succeeded.
        """
        if category not in self.state["completed_categories"]:
            self.state["completed_categories"].append(category)

        # Remove from failed_categories if it was previously there
        if category in self.state["failed_categories"]:
            self.state["failed_categories"] = [c for c in self.state["failed_categories"] if c != category]

        self.state["last_completed_category"] = category
        self.state["current_category"] = ""
        self.state["last_checkpoint_timestamp"] = datetime.now().isoformat()
        self.state["excel_row_count"] = excel_row_count
        self.state["database_record_count"] = database_record_count
        self.save()
        logger.info(f"Progress recorded: '{category}' marked completed in {self.progress_path}")

    def mark_failed(self, category: str) -> None:
        if category not in self.state["failed_categories"]:
            self.state["failed_categories"].append(category)
        self.state["current_category"] = ""
        self.save()
        logger.warning(f"Progress recorded: '{category}' marked failed in {self.progress_path}")

    def is_category_completed(self, category: str) -> bool:
        norm = category.strip().lower()
        return any(c.strip().lower() == norm for c in self.state.get("completed_categories", []))

    def get_completed_categories(self) -> List[str]:
        return list(self.state.get("completed_categories", []))

    def get_summary(self) -> Dict[str, Any]:
        return dict(self.state)
