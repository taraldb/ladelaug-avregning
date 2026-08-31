from pathlib import Path

import pytest

from ladelaug_avregning.config import load_config

EXAMPLE = Path("config/config.example.yaml")


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_example_with_secret_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LADELAUG_SECRET_KEY", "s3cr3t")
    monkeypatch.delenv("LADELAUG_TRUSTED_PROXIES", raising=False)
    monkeypatch.chdir(tmp_path)  # so the stray .env reader finds nothing
    cfg = load_config(Path(__file__).resolve().parents[2] / EXAMPLE)
    assert cfg.auth.secret_key == "s3cr3t"
    assert cfg.timezone == "Europe/Oslo"
    assert cfg.server.port == 8080
    assert cfg.server.trusted_proxies == "127.0.0.1"


def test_trusted_proxies_wildcard_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LADELAUG_SECRET_KEY", "x")
    monkeypatch.delenv("LADELAUG_TRUSTED_PROXIES", raising=False)
    monkeypatch.chdir(tmp_path)
    path = _write(tmp_path, "server:\n  trusted_proxies: '*'\n")
    with pytest.raises(ValueError) as exc:
        load_config(path)
    assert "trusted_proxies" in str(exc.value)


def test_trusted_proxies_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LADELAUG_SECRET_KEY", "x")
    monkeypatch.setenv("LADELAUG_TRUSTED_PROXIES", "10.0.0.0/8")
    monkeypatch.chdir(tmp_path)
    path = _write(tmp_path, "server:\n  trusted_proxies: '*'\n")
    cfg = load_config(path)
    assert cfg.server.trusted_proxies == "10.0.0.0/8"


def test_missing_file_hint(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        load_config(tmp_path / "nope.yaml")
    assert "config.example.yaml" in str(exc.value)


def test_blank_secret_without_env_is_error(tmp_path, monkeypatch):
    monkeypatch.delenv("LADELAUG_SECRET_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    path = _write(tmp_path, "auth:\n  secret_key: ''\n")
    with pytest.raises(ValueError) as exc:
        load_config(path)
    assert "secret_key" in str(exc.value)


def test_secret_env_satisfies(tmp_path, monkeypatch):
    monkeypatch.setenv("LADELAUG_SECRET_KEY", "from-env")
    monkeypatch.chdir(tmp_path)
    path = _write(tmp_path, "auth:\n  secret_key: ''\n")
    cfg = load_config(path)
    assert cfg.auth.secret_key == "from-env"


def test_bad_timezone(tmp_path, monkeypatch):
    monkeypatch.setenv("LADELAUG_SECRET_KEY", "x")
    monkeypatch.chdir(tmp_path)
    path = _write(tmp_path, "timezone: 'Mars/Olympus'\n")
    with pytest.raises(ValueError) as exc:
        load_config(path)
    assert "time zone" in str(exc.value)


def test_bad_log_level(tmp_path, monkeypatch):
    monkeypatch.setenv("LADELAUG_SECRET_KEY", "x")
    monkeypatch.chdir(tmp_path)
    path = _write(tmp_path, "logging:\n  level: 'LOUD'\n")
    with pytest.raises(ValueError) as exc:
        load_config(path)
    assert "logging.level" in str(exc.value)


def test_argon2_memory_floor(tmp_path, monkeypatch):
    monkeypatch.setenv("LADELAUG_SECRET_KEY", "x")
    monkeypatch.chdir(tmp_path)
    path = _write(tmp_path, "auth:\n  argon2_memory_cost_kib: 1024\n")
    with pytest.raises(ValueError) as exc:
        load_config(path)
    assert "argon2_memory_cost_kib" in str(exc.value)


def test_gmail_backend_without_secrets_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LADELAUG_SECRET_KEY", "x")
    for var in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    path = _write(tmp_path, "email:\n  backend: 'gmail'\n")
    with pytest.raises(ValueError) as exc:
        load_config(path)
    assert "gmail_refresh_token" in str(exc.value)


def test_gmail_backend_secrets_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LADELAUG_SECRET_KEY", "x")
    monkeypatch.setenv("GMAIL_CLIENT_ID", "cid")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "rtoken")
    monkeypatch.chdir(tmp_path)
    path = _write(tmp_path, "email:\n  backend: 'gmail'\n")
    cfg = load_config(path)
    assert cfg.email.gmail_client_id == "cid"
    assert cfg.email.gmail_client_secret == "csecret"
    assert cfg.email.gmail_refresh_token == "rtoken"


def test_unknown_email_backend_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LADELAUG_SECRET_KEY", "x")
    monkeypatch.chdir(tmp_path)
    path = _write(tmp_path, "email:\n  backend: 'carrier-pigeon'\n")
    with pytest.raises(ValueError) as exc:
        load_config(path)
    assert "email.backend" in str(exc.value)


def test_multiple_problems_joined(tmp_path, monkeypatch):
    monkeypatch.delenv("LADELAUG_SECRET_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    path = _write(
        tmp_path,
        "timezone: 'Mars/Olympus'\nlogging:\n  level: 'LOUD'\nauth:\n  secret_key: ''\n",
    )
    with pytest.raises(ValueError) as exc:
        load_config(path)
    msg = str(exc.value)
    assert "secret_key" in msg and "time zone" in msg and "logging.level" in msg
