import subprocess

import pytest


def get_all_revisions():
    result = subprocess.run(["alembic", "history"], stdout=subprocess.PIPE, check=True)
    lines = result.stdout.decode().splitlines()
    revisions = []
    for line in lines:
        if line and "->" in line:
            rev = line.split("->")[0].strip()
            if rev != "<base>":
                revisions.append(rev)
    return list(reversed(revisions))


@pytest.mark.parametrize("rev", get_all_revisions())
def test_stairway_upgrade_downgrade(rev):
    # upgrade к ревизии
    subprocess.check_call(["alembic", "upgrade", rev])
    # downgrade на шаг
    subprocess.check_call(["alembic", "downgrade", "-1"])
    # upgrade обратно
    subprocess.check_call(["alembic", "upgrade", rev])
