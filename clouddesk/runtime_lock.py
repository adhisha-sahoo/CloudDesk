from pathlib import Path


class RuntimeLock:
    """Prevent two embedded schedulers from recovering each other's in-flight jobs."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("a+b")
        self.handle.seek(0)
        self.handle.write(b"0")
        self.handle.flush()
        self.handle.seek(0)
        try:
            try:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except ImportError:
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            self.handle.close()
            raise RuntimeError(
                "Another CloudDesk process owns this data directory. Use one worker."
            ) from error

    def close(self):
        self.handle.close()
