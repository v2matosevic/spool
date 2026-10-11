import importlib.util
from pathlib import Path
import subprocess

import pytest


spec = importlib.util.spec_from_file_location(
    'release_verification', Path(__file__).resolve().parents[1] / 'scripts' / 'verify_release.py'
)
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


def failure(message):
    return subprocess.CalledProcessError(1, ['hdiutil', 'verify'], stderr=message)


def test_temporary_disk_image_lock_is_retried(monkeypatch):
    responses = iter([
        failure('hdiutil: verify failed - Resource temporarily unavailable'),
        subprocess.CompletedProcess(['hdiutil'], 0, stdout='checksum valid\n'),
    ])
    calls, delays = [], []

    def run(command, **options):
        calls.append(command)
        assert options == {'check': True, 'capture_output': True, 'text': True}
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(verification.subprocess, 'run', run)
    monkeypatch.setattr(verification.time, 'sleep', delays.append)
    verification.verify_disk_image(Path('Spool.dmg'))
    assert len(calls) == 2
    assert delays == [2]


def test_invalid_disk_image_fails_without_retry(monkeypatch):
    calls, delays = [], []

    def run(command, **options):
        calls.append(command)
        raise failure('hdiutil: verify failed - image checksum mismatch')

    monkeypatch.setattr(verification.subprocess, 'run', run)
    monkeypatch.setattr(verification.time, 'sleep', delays.append)
    with pytest.raises(subprocess.CalledProcessError):
        verification.verify_disk_image(Path('Spool.dmg'))
    assert len(calls) == 1
    assert delays == []


def test_persistent_disk_image_lock_still_fails(monkeypatch):
    calls, delays = [], []

    def run(command, **options):
        calls.append(command)
        raise failure('Resource temporarily unavailable')

    monkeypatch.setattr(verification.subprocess, 'run', run)
    monkeypatch.setattr(verification.time, 'sleep', delays.append)
    with pytest.raises(subprocess.CalledProcessError):
        verification.verify_disk_image(Path('Spool.dmg'))
    assert len(calls) == 3
    assert delays == [2, 4]
