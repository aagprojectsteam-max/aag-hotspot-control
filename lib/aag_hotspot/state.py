"""Root-owned runtime journal and fixed-path credential storage."""
from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import stat
import time
import uuid
from . import ownership as rb
from .policy import TABLE, STA, validate_password

RUNTIME = Path('/run/aag-hotspot')
PRIVATE = RUNTIME / 'private'
PERSISTENT = Path('/var/lib/aag-hotspot')
LOCK_WAIT = 10.0
RECOVERY_LOCK_WAIT = 30.0
LOCK_POLL = 0.05


def lock_holder(fd):
    """Kernel evidence only; a PID is diagnostic, never cleanup authorization."""
    st = os.fstat(fd)
    key = (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)
    try:
        for row in Path('/proc/locks').read_text().splitlines():
            fields = row.split()
            if len(fields) != 8 or fields[1:4] != ['FLOCK', 'ADVISORY', 'WRITE']:
                continue
            major, minor, inode = fields[5].split(':')
            if (int(major, 16), int(minor, 16), int(inode)) == key:
                return 'kernel_pid=' + str(int(fields[4]))
    except (OSError, ValueError):
        pass
    return 'kernel_owner=unavailable_or_released'


def trusted_dir(path, mode):
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or stat.S_IMODE(st.st_mode) != mode:
        raise rb.SafetyError('Unsafe application state directory')


def secure_read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as f:
        rb.verify_private(os.fstat(f.fileno()))
        return json.load(f, object_pairs_hook=rb.reject_duplicates)


def atomic_json(path, data, mode=0o600):
    temp = path.parent / ('.aag-write-' + uuid.uuid4().hex)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    os.fchmod(fd, mode)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        d = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(d)
        finally: os.close(d)
    finally:
        if temp.exists(): temp.unlink()


class ProductionOwner(rb.Ownership):
    @property
    def profile_name(self):
        return 'AAG Hotspot ' + self.test_id


def owner_for(state, boot_id):
    rb.exact_keys(state, ('schema', 'ownership', 'phase', 'mode', 'radio_touched',
                          'auto_touched', 'guard_digest'))
    if type(state['schema']) is not int or state['schema'] != 1:
        raise rb.SafetyError('Invalid session schema')
    if state['phase'] not in ('starting', 'switching', 'active', 'stopping') or state['mode'] not in ('local', 'internet'):
        raise rb.SafetyError('Invalid session phase/mode')
    if any(type(state[k]) is not bool for k in ('radio_touched', 'auto_touched')):
        raise rb.SafetyError('Invalid restoration journal')
    digest = state['guard_digest']
    if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)):
        raise rb.SafetyError('Invalid guard receipt')
    legacy = rb.validate_manifest(state['ownership'], boot_id)
    if state['auto_touched'] and not legacy.baseline_autoconnect:
        raise rb.SafetyError('Autoconnect journal conflicts with baseline')
    values = asdict(legacy)
    values.update(vif='aaghp' + uuid.UUID(legacy.test_id).hex[:8], table=TABLE,
                  marker='AAG-Hotspot-Control session=' + legacy.test_id,
                  restore_radio=False, restore_autoconnect=False)
    owner = ProductionOwner(**values)
    if owner.vif in state['ownership']['baseline']['interface_names']:
        raise rb.SafetyError('Production VIF was already present')
    return owner


class Store:
    def __init__(self):
        self.boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()

    @contextmanager
    def locked(self, create=False, timeout=LOCK_WAIT):
        # Only lock acquisition is polled, never the operation itself. Foreground
        # requests wait across short supervisor checks; the supervisor uses zero.
        # The same-operation Controller.stop() stays inside this context and must
        # not acquire a second flock (even a second fd in this PID would conflict).
        if not isinstance(timeout, (int, float)) or not 0 <= timeout <= RECOVERY_LOCK_WAIT:
            raise ValueError('Invalid operation lock timeout')
        if os.geteuid() != 0:
            raise rb.SafetyError('Administrator backend execution required')
        for parent in (Path('/run'), Path('/var'), Path('/var/lib')):
            st = parent.lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or stat.S_IMODE(st.st_mode) & 0o022:
                raise rb.SafetyError('Untrusted system parent directory')
        if not os.path.lexists(RUNTIME):
            if not create:
                yield False
                return
            RUNTIME.mkdir(mode=0o755)
            RUNTIME.chmod(0o755)
        trusted_dir(RUNTIME, 0o755)
        if not os.path.lexists(PRIVATE):
            if not create:
                yield False
                return
            PRIVATE.mkdir(mode=0o700)
        trusted_dir(PRIVATE, 0o700)
        fd = os.open(PRIVATE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            end = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    remaining = end - time.monotonic()
                    if remaining <= 0:
                        raise rb.OperationError(
                            'BUSY: another hotspot operation is in progress; '
                            + lock_holder(fd) + '; wait_seconds=' + str(timeout)) from None
                    time.sleep(min(LOCK_POLL, remaining))
            yield True
        # Directory inode remains in place: unlink/recreate would split the lock.
        # Close (including signal exceptions/process death) releases kernel flock;
        # neither session.json nor PID metadata is used to decide lock ownership.
        finally: os.close(fd)

    def load(self):
        try: data = secure_read(PRIVATE / 'session.json')
        except FileNotFoundError: return None
        owner_for(data, self.boot_id)
        return data

    def save(self, data):
        owner_for(data, self.boot_id)
        atomic_json(PRIVATE / 'session.json', data)

    def clear(self):
        (PRIVATE / 'session.json').unlink(missing_ok=True)

    def publish(self, data):
        atomic_json(RUNTIME / 'status.json', data, 0o644)

    def configured(self):
        try:
            self.password()
            return True
        except FileNotFoundError: return False

    def password(self):
        trusted_dir(PERSISTENT, 0o755)
        data = secure_read(PERSISTENT / 'credentials.json')
        rb.exact_keys(data, ('schema', 'password'))
        if type(data['schema']) is not int or data['schema'] != 1:
            raise rb.SafetyError('Invalid credential schema')
        return validate_password(data['password'])

    def configure(self, password):
        validate_password(password)
        if not os.path.lexists(PERSISTENT):
            PERSISTENT.mkdir(mode=0o755)
            PERSISTENT.chmod(0o755)
        trusted_dir(PERSISTENT, 0o755)
        atomic_json(PERSISTENT / 'credentials.json', {'schema': 1, 'password': password})
