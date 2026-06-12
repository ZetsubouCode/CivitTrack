import csv
from io import StringIO

from .compare_service import compare_snapshots


def comparison_csv(from_id: int, to_id: int) -> tuple[str, str]:
    comparison = compare_snapshots(from_id, to_id)
    output = StringIO(newline="")
    fields = [
        "status",
        "model_id",
        "model_name",
        "model_type",
        "base_model",
        "page_url",
        "old_download_count",
        "new_download_count",
        "download_count_delta",
        "old_reaction_count",
        "new_reaction_count",
        "reaction_count_delta",
        "old_collected_count",
        "new_collected_count",
        "collected_count_delta",
        "old_generation_count",
        "new_generation_count",
        "generation_count_delta",
        "old_comment_count",
        "new_comment_count",
        "comment_count_delta",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(comparison["models"])
    writer.writerows(comparison["missing_models"])
    return output.getvalue(), f"civittrack_compare_{from_id}_{to_id}.csv"
