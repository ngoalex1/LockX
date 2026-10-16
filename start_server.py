"""Start the API/worker on one persistent volume as an unprivileged user."""
import os
from pathlib import Path


def prepare_volume():
    mount = os.getenv('RAILWAY_VOLUME_MOUNT_PATH')
    data = os.getenv('LOCKX_DATA_DIR') or (str(Path(mount)/'lockx') if mount else '.lockx-data')
    root = Path(data)
    root.mkdir(parents=True,exist_ok=True)
    # The volume can arrive owned by root. Grant only this service's account access.
    # Chromium's sandbox stays enabled; do not run the API/browser as root.
    if os.name == 'posix' and os.geteuid() == 0 and Path('/home/lockx').is_dir():
        import pwd
        account = pwd.getpwnam('lockx')
        for path in [root,*root.rglob('*')]:
            if path.is_symlink():
                raise RuntimeError('Unexpected symlink in private data volume')
            os.chown(path,account.pw_uid,account.pw_gid)
        os.chmod(root,0o700)
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)


if __name__ == '__main__':
    prepare_volume()
    import uvicorn
    uvicorn.run('main:app',host='0.0.0.0',port=int(os.getenv('PORT','8080')))
