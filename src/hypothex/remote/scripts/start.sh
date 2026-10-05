# start: reuse a healthy env server recorded in <home>/serve/server.json; fail
# when the recorded server runs on another host, or runs here but cannot be
# reused; else (no record, or its process is provably gone) start
# `nohup hx serve --host 127.0.0.1 --port 0 [--kind HX_KIND]` and wait
# until its descriptor answers. The new server's port comes from the server.json
# that `hx serve` writes with its own pid (Task 47), or, for an `hx serve` that
# writes none, from uvicorn's "Uvicorn running on" log line. Inputs: HX_HOME,
# optional HX_KIND (ssh | slurm); env HX_START_WAIT (seconds, default 30).
hx_expand_home
SERVE=$HX_HOME/serve
SJ=$SERVE/server.json
LOG=$SERVE/server.log
HX_BIN=$HX_HOME/runtime/bin/hx
DESCRIPTOR=/.well-known/hypothex/environment

# Preserve the entire file, including newlines, for strict local JSON validation.
# Shell extraction below is only a health comparison, never the trusted parser.
hx_emit_environment() {
    _env_hex=$(od -An -v -tx1 "$HX_HOME/environment.json") ||
        hx_fail "cannot read trusted environment identity"
    _env_hex=$(printf '%s' "$_env_hex" | tr -d ' \n') ||
        hx_fail "cannot encode trusted environment identity"
    echo "HX:environment_json_hex=$_env_hex"
    echo "HX:environment_id=$_env_id"
}

umask 077 # server.json holds the token: owner-only
mkdir -p "$SERVE" || hx_fail "cannot create $SERVE"
chmod 700 "$SERVE" 2>/dev/null || true
hx_lock "$SERVE/.lock"
_me=$(hostname 2>/dev/null || echo unknown)
_env_id=""
if [ -f "$HX_HOME/environment.json" ]; then
    _env_id=$(hx_json_str "$(tr -d '\n' <"$HX_HOME/environment.json")" environment_id)
fi

# One server per home, ever. A recorded server is reused when it answers for THIS
# home (a recycled port never matches); it is replaced only when its process is
# provably gone. A server on another login node (shared home), or a live one that
# cannot be reused, is never orphaned by starting a second one: the script fails.
if [ -f "$SJ" ]; then
    _j=$(tr -d '\n' <"$SJ")
    _pid=$(hx_json_num "$_j" pid)
    _port=$(hx_json_num "$_j" port)
    _host=$(hx_json_str "$_j" hostname)
    _birth=$(hx_json_str "$_j" pid_start)
    if [ -n "$_host" ] && [ "$_host" != "$_me" ]; then
        hx_fail "$SJ names a server that runs on $_host (pid ${_pid:-unknown}), not $_me; connect through $_host, or stop it there, then retry"
    fi
    if [ -n "$_pid" ] && hx_same_proc "$_pid" "$_birth"; then
        if [ -n "$_port" ] && [ -n "$_env_id" ] &&
            _d=$(hx_get "http://127.0.0.1:$_port$DESCRIPTOR" 2>/dev/null) &&
            [ "$(hx_json_str "$_d" environment_id)" = "$_env_id" ]; then
            hx_emit_environment
            echo "HX:reused=1"
            echo "HX:server=$_j"
            exit 0
        fi
        case $_j in
            *'"managed": true'* | *'"managed":true'*) _what="the hx server" ;;
            *) _what="an hx server that Hypothex did not start" ;;
        esac
        if [ -z "$_birth" ]; then
            _how="kill pid $_pid if it is that server, or remove $SJ if it is not, then retry"
        elif [ "$_what" = "the hx server" ]; then
            _how="stop it (hx hosts upgrade restarts it) and retry"
        else
            _how="stop it and retry"
        fi
        hx_fail "$_what in $SJ (pid $_pid) runs but does not answer for this home on port ${_port:-unknown}; $_how" "$LOG" 20
    fi
fi

[ -x "$HX_BIN" ] || hx_fail "hx is not installed at $HX_BIN; run the install step (hx hosts upgrade) first"

[ -f "$LOG" ] && mv -f "$LOG" "$LOG.1"
rm -f "$SJ" # the record of a server that is provably gone; the new server writes its own
if [ -n "${HX_KIND:-}" ]; then
    set -- --kind "$HX_KIND"
else
    set --
fi
HX_TOKEN=$(od -An -N24 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n')
[ -n "$HX_TOKEN" ] || hx_fail "cannot read /dev/urandom for the server token"
HYPOTHEX_HOME=$HX_HOME HYPOTHEX_SERVE_TOKEN=$HX_TOKEN \
    nohup "$HX_BIN" serve --host 127.0.0.1 --port 0 "$@" >"$LOG" 2>&1 </dev/null &
_pid=$!

hx_abort_start() {
    # hx_abort_start MESSAGE: stop the half-started server for good (SIGKILL if it
    # ignores SIGTERM), drop the record it may have written, and fail with the log.
    hx_stop_pid "$_pid" ""
    rm -f "$SJ.tmp"
    if [ -f "$SJ" ] && [ "$(hx_json_num "$(tr -d '\n' <"$SJ" 2>/dev/null)" pid)" = "$_pid" ]; then
        rm -f "$SJ"
    fi
    hx_fail "$1" "$LOG" 80
}

_wait=${HX_START_WAIT:-30}
_limit=$((_wait * 4))
_i=0
_desc=""
while [ "$_i" -lt "$_limit" ]; do
    if ! hx_alive "$_pid"; then
        hx_abort_start "hx serve exited during startup"
    fi
    _port=""
    if [ -f "$SJ" ]; then
        _j=$(tr -d '\n' <"$SJ" 2>/dev/null || true)
        if [ "$(hx_json_num "$_j" pid)" = "$_pid" ]; then
            _port=$(hx_json_num "$_j" port)
        fi
    fi
    if [ -z "$_port" ]; then
        _port=$(sed -n 's/.*Uvicorn running on http:\/\/127\.0\.0\.1:\([0-9][0-9]*\).*/\1/p' "$LOG" | tail -n 1)
    fi
    if [ -n "$_port" ] && _desc=$(hx_get "http://127.0.0.1:$_port$DESCRIPTOR" 2>/dev/null); then
        break
    fi
    _desc=""
    hx_sleep
    _i=$((_i + 1))
done

if [ -z "$_desc" ]; then
    hx_abort_start "hx serve was not ready after ${_wait}s"
fi

# Read again after startup: a new home did not have environment.json earlier.
_env_id=""
if [ -f "$HX_HOME/environment.json" ]; then
    _env_id=$(hx_json_str "$(tr -d '\n' <"$HX_HOME/environment.json")" environment_id)
fi
[ -n "$_env_id" ] && [ "$(hx_json_str "$_desc" environment_id)" = "$_env_id" ] ||
    hx_abort_start "server descriptor does not match the trusted environment identity"

_ver=$(hx_json_str "$_desc" hx_version)
_proto=$(hx_json_num "$_desc" protocol_version)
_birth=$(hx_pid_start "$_pid") # stop.sh signals only this exact process
# Preserve the CLI's exact process birth, home, environment, and token fields.
# Only managed and the shell process identity are added/changed here.
if [ -f "$SJ" ]; then
    _j=$(tr -d '\n' <"$SJ") || hx_abort_start "cannot read managed server record"
    [ "$(hx_json_num "$_j" pid)" = "$_pid" ] ||
        hx_abort_start "managed server record changed during startup"
    _managed=$(printf '%s\n' "$_j" | sed \
        -e 's/"managed": *false/"managed": true/' \
        -e "s/}[[:space:]]*$/, \"pid_start\": \"$_birth\"}/") ||
        hx_abort_start "cannot update managed server record"
    [ -n "$_managed" ] || hx_abort_start "cannot update managed server record"
    printf '%s\n' "$_managed" >"$SJ.tmp" || hx_abort_start "cannot write managed server record"
else
    printf '{"pid": %s, "port": %s, "managed": true, "hx_version": "%s", "protocol_version": %s, "hostname": "%s", "pid_start": "%s", "token": "%s", "environment_id": "%s"}\n' \
        "$_pid" "$_port" "$_ver" "${_proto:-0}" "$_me" "$_birth" "$HX_TOKEN" "$_env_id" >"$SJ.tmp" ||
        hx_abort_start "cannot write managed server record"
fi
mv -f "$SJ.tmp" "$SJ" || hx_abort_start "cannot write $SJ"
_j=$(cat "$SJ") || hx_abort_start "cannot read managed server record"
hx_emit_environment
echo "HX:reused=0"
echo "HX:server=$_j"
