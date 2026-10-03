#!/bin/sh
# Hypothex bootstrap prelude. Prepended to every script in this folder.
# Contract with bootstrap.py: results are stdout lines "HX:<key>=<value>";
# "HX:log=<line>" may repeat; "HX:error=<message>" means failure. Other
# stdout (login banners, rc-file noise) is ignored. Scripts exit 0 after
# reporting an error so the transport can tell script errors from ssh errors.

hx_fail() {
    # hx_fail MESSAGE [LOGFILE [LINES]]
    echo "HX:error=$1"
    if [ -n "${2:-}" ] && [ -f "$2" ]; then
        tail -n "${3:-80}" "$2" | sed 's/^/HX:log=/'
    fi
    exit 0
}

hx_expand_home() {
    case $HX_HOME in
        "~") HX_HOME=$HOME ;;
        "~/"*) HX_HOME=$HOME/${HX_HOME#"~/"} ;;
    esac
}

hx_sleep() {
    sleep 0.25 2>/dev/null || sleep 1
}

hx_alive() {
    # hx_alive PID: true when PID runs and is not a zombie.
    kill -0 "$1" 2>/dev/null || return 1
    case $(ps -o stat= -p "$1" 2>/dev/null) in
        Z*) return 1 ;;
    esac
    return 0
}

hx_pid_start() {
    # hx_pid_start PID: the birth of process PID (empty when unknown), so a
    # recycled pid never passes for the process that was recorded.
    if [ -r "/proc/$1/stat" ]; then
        sed 's/.*) //' "/proc/$1/stat" 2>/dev/null | cut -d' ' -f20
    else
        ps -o lstart= -p "$1" 2>/dev/null | tr -s ' ' | sed 's/^ //;s/ $//'
    fi
}

hx_same_proc() {
    # hx_same_proc PID START: PID runs, and when START is known it is the same birth.
    hx_alive "$1" || return 1
    [ -z "$2" ] || [ "$(hx_pid_start "$1")" = "$2" ]
}

hx_stop_pid() {
    # hx_stop_pid PID START: SIGTERM PID (only while hx_same_proc PID START holds),
    # wait up to 10 s, then SIGKILL it if it still runs.
    hx_same_proc "$1" "$2" || return 0
    kill "$1" 2>/dev/null
    _hx_i=0
    while hx_same_proc "$1" "$2" && [ "$_hx_i" -lt 40 ]; do
        hx_sleep
        _hx_i=$((_hx_i + 1))
    done
    if hx_same_proc "$1" "$2"; then
        kill -9 "$1" 2>/dev/null
    fi
    return 0
}

hx_owner_dead() {
    # hx_owner_dead OWNER: true only when OWNER ("host|pid|birth") ran on this host
    # and that process is gone, or its pid now names a process with another birth.
    # An empty owner, or one on another host (a shared home), cannot be checked:
    # it is never dead.
    [ -n "$1" ] || return 1
    _hx_oh=${1%%|*}
    _hx_or=${1#*|}
    [ "$_hx_oh" = "$(hostname 2>/dev/null || echo unknown)" ] || return 1
    ! hx_same_proc "${_hx_or%%|*}" "${_hx_or#*|}"
}

# Lock helpers (one process each). Arguments: PATH OKFLAG PARENT_PID WAIT_SECONDS.
# Each takes the lock, creates OKFLAG, and holds the lock until PARENT_PID is gone.
# Exit 1: the lock stayed busy for WAIT_SECONDS; any other exit: it could not lock.
HX_FLOCK_HOLD='exec 9>>"$1" || exit 2
flock -w "$4" 9 || exit "$(( $? == 1 ? 1 : 2 ))"
: >"$2"
while kill -0 "$3" 2>/dev/null; do sleep 0.2 9>&- 2>/dev/null || sleep 1 9>&-; done'
HX_PY_LOCK='import fcntl, os, sys, time
path, flag, parent, limit = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
deadline = time.monotonic() + limit
while True:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
    except BlockingIOError:
        if time.monotonic() >= deadline:
            sys.exit(1)
        time.sleep(0.2)
    except OSError:
        sys.exit(2)
open(flag, "w").close()
while os.getppid() == parent:
    time.sleep(0.2)'

hx_unlock() {
    # Release the lock taken by hx_lock (EXIT trap): stop the OS-lock helper, or
    # remove the mkdir lock (no one can have broken it while its owner lived).
    if [ -n "${HX_LOCKER:-}" ]; then
        kill "$HX_LOCKER" 2>/dev/null
        wait "$HX_LOCKER" 2>/dev/null
        HX_LOCKER=""
    fi
    if [ -n "${HX_HELD_LOCK:-}" ]; then
        rm -rf "$HX_HELD_LOCK"
        HX_HELD_LOCK=""
    fi
}

hx_mkdir_lock() {
    # hx_mkdir_lock DIR: the fallback on a host without flock and python3. DIR/owner
    # is "host|pid|birth". A waiter breaks the lock only when hx_owner_dead proves
    # its owner gone, and only under DIR.break after reading the owner again, so
    # two waiters never both break it and a lock someone just took is never removed.
    # A live owner, another host's owner, or a lock without an owner line is never
    # broken: after HX_LOCK_WAIT seconds the script fails and names DIR.
    _hx_waited=0
    _hx_token="$(hostname 2>/dev/null || echo unknown)|$$|$(hx_pid_start $$)"
    while ! mkdir "$1" 2>/dev/null; do
        if [ -f "$1" ] && rm -f "$1" 2>/dev/null; then
            # A regular file is the lock file a flock/python3 run left (the OS lock
            # goes with its holder, the file stays). This node has neither tool, so
            # no OS lock on it can be held from here: it only blocks the mkdir.
            continue
        fi
        _hx_owner=$(cat "$1/owner" 2>/dev/null || true)
        if hx_owner_dead "$_hx_owner" && mkdir "$1.break" 2>/dev/null; then
            if [ "$(cat "$1/owner" 2>/dev/null || true)" = "$_hx_owner" ]; then
                rm -rf "$1"
            fi
            rmdir "$1.break" 2>/dev/null || true
            continue
        fi
        if [ "$_hx_waited" -ge "$_hx_limit" ]; then
            hx_fail "lock $1 is held by ${_hx_owner:-an unknown process}; waited ${_hx_limit}s (it is broken only when its owner ran on this host and is gone; remove $1 if no hx runs there)"
        fi
        sleep 1
        _hx_waited=$((_hx_waited + 1))
    done
    echo "$_hx_token" >"$1/owner"
    HX_HELD_LOCK=$1
}

hx_lock() {
    # hx_lock PATH: an exclusive lock held until the script exits (EXIT trap). With
    # flock(1), else python3, an OS lock on the file PATH, held by a helper process
    # that exits with this script: the OS drops the lock when its holder dies, so it
    # is never broken or stolen. Without either tool (or while a mkdir lock folder
    # is at PATH): hx_mkdir_lock. Sets HX_LOCK_MODE. Waits HX_LOCK_WAIT seconds
    # (default 300), at most HX_LOCK_LIMIT (bootstrap.py sets it below its ssh
    # timeout, so a busy lock fails here with a clear message, not as an ssh timeout).
    _hx_limit=${HX_LOCK_WAIT:-300}
    if [ -n "${HX_LOCK_LIMIT:-}" ] && [ "$HX_LOCK_LIMIT" -lt "$_hx_limit" ]; then
        _hx_limit=$HX_LOCK_LIMIT
    fi
    if [ -d "$1" ]; then
        HX_LOCK_MODE=mkdir
    elif command -v flock >/dev/null 2>&1; then
        HX_LOCK_MODE=flock
    elif command -v python3 >/dev/null 2>&1; then
        HX_LOCK_MODE=python3
    else
        HX_LOCK_MODE=mkdir
    fi
    if [ "$HX_LOCK_MODE" = mkdir ]; then
        hx_mkdir_lock "$1"
    else
        _hx_ok="$1.ok.$$"
        rm -f "$_hx_ok"
        if [ "$HX_LOCK_MODE" = flock ]; then
            sh -c "$HX_FLOCK_HOLD" hx-lock "$1" "$_hx_ok" "$$" "$_hx_limit" \
                </dev/null >/dev/null 2>&1 &
        else
            python3 -c "$HX_PY_LOCK" "$1" "$_hx_ok" "$$" "$_hx_limit" \
                </dev/null >/dev/null 2>&1 &
        fi
        HX_LOCKER=$!
        while [ ! -e "$_hx_ok" ]; do
            if ! hx_alive "$HX_LOCKER"; then
                wait "$HX_LOCKER"
                _hx_rc=$?
                HX_LOCKER=""
                if [ "$_hx_rc" = 1 ]; then
                    hx_fail "lock $1 is held by another hx process; waited ${_hx_limit}s"
                fi
                hx_fail "cannot lock $1 with $HX_LOCK_MODE (exit $_hx_rc); does this filesystem support locks?"
            fi
            hx_sleep
        done
        rm -f "$_hx_ok"
    fi
    trap 'hx_unlock' EXIT
}

hx_find_uv() {
    for _hx_c in "$(command -v uv 2>/dev/null)" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -n "$_hx_c" ] && [ -x "$_hx_c" ]; then
            echo "$_hx_c"
            return 0
        fi
    done
    return 1
}

hx_get() {
    # hx_get URL: print the body of a local HTTP GET (no proxy).
    if command -v curl >/dev/null 2>&1; then
        curl -fsS --noproxy '*' --max-time 3 "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- --no-proxy -T 3 "$1"
    else
        NO_PROXY='*' no_proxy='*' python3 -c 'import sys, urllib.request
sys.stdout.write(urllib.request.urlopen(sys.argv[1], timeout=3).read().decode())' "$1"
    fi
}

hx_json_str() {
    # hx_json_str JSON KEY: string value of KEY in one-line JSON.
    printf '%s\n' "$1" | sed -n "s/.*\"$2\": *\"\([^\"]*\)\".*/\1/p"
}

hx_json_num() {
    # hx_json_num JSON KEY: integer value of KEY in one-line JSON.
    printf '%s\n' "$1" | sed -n "s/.*\"$2\": *\([0-9][0-9]*\).*/\1/p"
}
