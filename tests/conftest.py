import pytest


@pytest.fixture(autouse=True)
def plotlook_home(tmp_path, monkeypatch):
    """saved presets and the dialogs' memory go into the test's folder"""
    monkeypatch.setenv('PLOTLOOK_HOME', str(tmp_path / 'plotlook-home'))
