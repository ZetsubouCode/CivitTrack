from io import BytesIO

from flask import Flask, jsonify, render_template, request, Response, send_file

from services.backup_service import create_download_backup, MAX_RESTORE_BYTES, restore_database
from services.compare_service import (
    compare_by_datetime,
    compare_latest_previous,
    compare_snapshots,
    get_latest_breakdown,
    get_model_history,
    list_snapshots,
)
from services.config import get_config
from services.db import init_db, list_sync_logs
from services.export_service import comparison_csv
from services.snapshot_service import delete_snapshot, take_snapshot


APP_VERSION = "2.1.4"
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
            "app_version": APP_VERSION,
        }
    )


@app.post("/api/snapshot")
def snapshot():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Snapshot request must be a JSON object."}), 400
    try:
        result = take_snapshot(note=payload.get("note"))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify(result), 200 if result["ok"] else 400


@app.get("/api/snapshots")
def snapshots():
    return jsonify({"snapshots": list_snapshots()})


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


if __name__ == "__main__":
    config = get_config()
    app.run(host=config.app_host, port=config.app_port, debug=False)
