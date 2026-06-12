import sqlite3
from io import BytesIO

from flask import Flask, jsonify, render_template, request, Response, send_file

from services.alert_service import list_alerts, mark_alert_read, mark_all_alerts_read
from services.article_service import latest_article_summary, list_articles, run_article_sync
from services.backup_service import create_download_backup, MAX_RESTORE_BYTES, restore_database
from services.buzz_service import (
    get_buzz_settings,
    get_buzz_transaction_detail,
    latest_buzz_summary,
    list_buzz_checks,
    list_buzz_transactions,
    run_buzz_check,
    update_buzz_settings,
)
from services.compare_service import (
    compare_by_datetime,
    compare_latest_previous,
    compare_snapshots,
    get_latest_breakdown,
    get_model_history,
    list_snapshots,
)
from services.civitai_client import CivitaiError
from services.config import get_config, list_env_settings, update_env_settings
from services.db import init_db, list_sync_logs
from services.export_service import comparison_csv
from services.image_cache_service import (
    ImageCacheError,
    clear_image_cache,
    get_cached_image,
    image_cache_status,
)
from services.image_service import (
    get_model_image_detail,
    get_reaction_usage,
    latest_image_summary,
    list_image_models,
    list_model_images,
    post_comment_reply,
    post_image_comment,
    run_image_sync,
    sync_hidden_images,
    toggle_comment_reaction,
    toggle_image_reaction,
)
from services.quality_service import get_snapshot_quality
from services.settings_service import get_alert_settings, update_alert_settings
from services.snapshot_service import delete_snapshot, take_snapshot


APP_VERSION = "2.5.0"
app = Flask(__name__)
app.config["SECRET_KEY"] = get_config().secret_key
app.config["MAX_CONTENT_LENGTH"] = MAX_RESTORE_BYTES
app.jinja_env.globals["app_version"] = APP_VERSION
init_db()


def _int_arg(name: str) -> int:
    try:
        return int(request.args[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _json_action(action):
    try:
        return jsonify(action())
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify({"ok": False, "error": "Backup upload is larger than the 256 MB restore limit."}), 413


@app.get("/")
def dashboard():
    return render_template("dashboard.html")


@app.get("/api/status")
def status():
    config = get_config()
    snapshots = list_snapshots(config.username)
    latest = snapshots[0] if snapshots else None
    return jsonify(
        {
            "username": config.username,
            "api_key_configured": config.api_key_configured,
            "db_path": str(config.db_path),
            "model_type_filter": config.model_type_filter,
            "include_nsfw": config.include_nsfw,
            "include_minor": config.include_minor,
            "last_snapshot": latest["checked_at"] if latest else None,
            "last_totals": latest,
            "latest_quality_status": latest["quality_status"] if latest else None,
            "latest_quality_warning_count": latest["warning_count"] if latest else 0,
            "database_ready": config.db_path.exists(),
            "model_type_filter_configured": bool(config.model_types),
            "cli_scheduler_available": True,
            "app_version": APP_VERSION,
        }
    )


@app.get("/api/settings")
def settings():
    return jsonify(list_env_settings())


@app.post("/api/settings")
def settings_update():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Settings request must be a JSON object."}), 400
    previous_config = get_config()
    try:
        result = update_env_settings(payload.get("values"), payload.get("clear_secrets"))
        current_config = get_config()
        if current_config.db_path != previous_config.db_path:
            init_db()
        app.config["SECRET_KEY"] = current_config.secret_key
    except (OSError, sqlite3.Error, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, **result})


@app.post("/api/snapshot")
def snapshot():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Snapshot request must be a JSON object."}), 400
    try:
        result = take_snapshot(note=payload.get("note"), note_type=payload.get("note_type"))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify(result), 200 if result["ok"] else 400


@app.get("/api/snapshots")
def snapshots():
    return jsonify({"snapshots": list_snapshots()})


@app.get("/api/snapshot-quality")
def snapshot_quality():
    return _json_action(lambda: get_snapshot_quality(_int_arg("snapshot_id")))


@app.delete("/api/snapshots/<int:snapshot_id>")
def snapshot_delete(snapshot_id: int):
    return _json_action(lambda: delete_snapshot(snapshot_id))


@app.get("/api/database-backup")
def database_backup():
    temp_path, filename = create_download_backup()
    try:
        content = temp_path.read_bytes()
    finally:
        temp_path.unlink(missing_ok=True)
    return send_file(
        BytesIO(content),
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.sqlite3",
    )


@app.post("/api/database-restore")
def database_restore():
    return _json_action(lambda: restore_database(request.files.get("backup")))


@app.get("/api/latest-breakdown")
def latest_breakdown():
    return jsonify(get_latest_breakdown())


@app.get("/api/compare")
def compare():
    return _json_action(lambda: compare_snapshots(_int_arg("from_id"), _int_arg("to_id")))


@app.get("/api/compare-latest")
def compare_latest():
    return _json_action(compare_latest_previous)


@app.get("/api/compare-by-date")
def compare_date():
    return _json_action(
        lambda: compare_by_datetime(request.args.get("from_dt", ""), request.args.get("to_dt", ""))
    )


@app.get("/api/model-history")
def model_history():
    return _json_action(lambda: get_model_history(_int_arg("model_id")))


@app.get("/api/export-csv")
def export_csv():
    try:
        content, filename = comparison_csv(_int_arg("from_id"), _int_arg("to_id"))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return Response(
        content,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/logs")
def logs():
    return jsonify({"logs": list_sync_logs()})


@app.get("/api/alerts")
def alerts():
    return jsonify(list_alerts())


@app.post("/api/alerts/<int:alert_id>/read")
def alert_read(alert_id: int):
    return _json_action(lambda: mark_alert_read(alert_id))


@app.post("/api/alerts/read-all")
def alerts_read_all():
    return _json_action(mark_all_alerts_read)


@app.get("/api/alert-settings")
def alert_settings():
    return jsonify(get_alert_settings())


@app.post("/api/alert-settings")
def alert_settings_update():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, "settings": update_alert_settings(payload)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/api/buzz/status")
def buzz_status():
    return jsonify(latest_buzz_summary())


@app.post("/api/buzz/check")
def buzz_check():
    result = run_buzz_check()
    return jsonify(result), 200 if result["ok"] else 400


@app.get("/api/buzz/checks")
def buzz_checks():
    return _json_action(lambda: {"checks": list_buzz_checks(request.args.get("limit", 50))})


@app.get("/api/buzz/summary")
def buzz_summary():
    return jsonify(latest_buzz_summary())


@app.get("/api/buzz/transactions")
def buzz_transactions():
    return jsonify({"transactions": list_buzz_transactions(request.args)})


@app.get("/api/buzz/transaction-detail")
def buzz_transaction_detail():
    return _json_action(lambda: get_buzz_transaction_detail(_int_arg("id")))


@app.get("/api/buzz-settings")
def buzz_settings():
    return jsonify(get_buzz_settings())


@app.post("/api/buzz-settings")
def buzz_settings_update():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, "settings": update_buzz_settings(payload)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/api/images/status")
def images_status():
    hidden_sync = {"ok": False, "error": ""}
    try:
        hidden_sync = sync_hidden_images(source="status")
    except (CivitaiError, ValueError) as exc:
        hidden_sync = {"ok": False, "error": str(exc)}
    return jsonify({**latest_image_summary(), "cache": image_cache_status(), "hidden_sync": hidden_sync})


@app.post("/api/images/sync")
def images_sync():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Image sync request must be a JSON object."}), 400
    result = run_image_sync(
        pages_per_version=payload.get("pages_per_version", 1),
        with_meta=bool(payload.get("with_meta", False)),
        model_id=payload.get("model_id"),
        model_version_id=payload.get("model_version_id"),
        max_versions=payload.get("max_versions", 12),
    )
    return jsonify(result), 200 if result["ok"] else 400


@app.get("/api/images")
def images_list():
    return jsonify(list_model_images(request.args))


@app.get("/api/images/filters")
def images_filters():
    return jsonify(list_image_models(request.args))


@app.get("/api/images/detail")
def images_detail():
    return _json_action(lambda: get_model_image_detail(_int_arg("image_id")))


@app.post("/api/images/reaction")
def images_reaction():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Reaction request must be a JSON object."}), 400
    try:
        return jsonify(toggle_image_reaction(payload.get("image_id"), payload.get("reaction")))
    except (CivitaiError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/api/images/reaction-usage")
def images_reaction_usage():
    return jsonify(get_reaction_usage())


@app.post("/api/images/comment")
def images_comment():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Comment request must be a JSON object."}), 400
    try:
        return jsonify(post_image_comment(payload.get("image_id"), payload.get("content", "")))
    except (CivitaiError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/images/comment-reply")
def images_comment_reply():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Reply request must be a JSON object."}), 400
    try:
        return jsonify(post_comment_reply(
            payload.get("image_id"),
            payload.get("comment_id"),
            payload.get("parent_thread_id"),
            payload.get("content", ""),
        ))
    except (CivitaiError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/images/comment-reaction")
def images_comment_reaction():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Comment reaction request must be a JSON object."}), 400
    try:
        return jsonify(toggle_comment_reaction(
            payload.get("image_id"),
            payload.get("comment_id"),
            payload.get("reaction"),
        ))
    except (CivitaiError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.delete("/api/images/cache")
def images_cache_clear():
    return jsonify(clear_image_cache())


@app.get("/api/images/cache/<int:image_id>")
def images_cache(image_id: int):
    try:
        cached = get_cached_image(image_id)
    except ImageCacheError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    return send_file(
        cached.path,
        mimetype=cached.mimetype,
        conditional=True,
        max_age=7 * 24 * 60 * 60,
    )


@app.get("/api/articles/status")
def articles_status():
    return jsonify(latest_article_summary())


@app.post("/api/articles/sync")
def articles_sync():
    result = run_article_sync()
    return jsonify(result), 200 if result["ok"] else 400


@app.get("/api/articles")
def articles_list():
    return jsonify(list_articles(request.args))


if __name__ == "__main__":
    config = get_config()
    app.run(host=config.app_host, port=config.app_port, debug=False)
