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
        "old_favorite_count",
        "new_favorite_count",
        "favorite_count_delta",
        "old_comment_count",
        "new_comment_count",
        "comment_count_delta",
        "old_rating_count",
        "new_rating_count",
        "rating_count_delta",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(comparison["models"])
    writer.writerows(comparison["missing_models"])
    return output.getvalue(), f"civittrack_compare_{from_id}_{to_id}.csv"
