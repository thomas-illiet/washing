from app.beat.celery import celery_app
from internal.infra.config.settings import get_settings


def test_beat_uses_configured_schedule_file() -> None:
    assert celery_app.conf.beat_schedule_filename == get_settings().celery_beat_schedule_path
