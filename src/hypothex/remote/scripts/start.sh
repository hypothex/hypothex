# start: reuse a healthy env server recorded in <home>/serve/server.json,
# else start `nohup hx serve --host 127.0.0.1 --port 0 [--kind HX_KIND]` and wait
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

umask 077 # server.json holds the token: owner-only
mkdir -p "$SERVE" || hx_fail "cannot create $SERVE"
chmod 700 "$SERVE" 2>/dev/null || true
hx_lock "$SERVE/.lock"
_me=$(hostname 2>/dev/null || echo unknown)
_env_id=""
if [ -f "$HX_HOME/environment.json" ]; then
    _env_id=$(hx_json_str "$(tr -d '\n' <"$HX_HOME/environment.json")" environment_id)
fi

if [ -f "$SJ" ]; then
    _j=$(tr -d '\n' <"$SJ")
    _pid=$(hx_json_num "$_j" pid)
    _port=$(hx_json_num "$_j" port)
    _host=$(hx_json_str "$_j" hostname)
    _birth=$(hx_json_str "$_j" pid_start)
    # reuse only a server that answers for THIS home: a recycled port never matches
    if [ -n "$_pid" ] && [ -n "$_port" ] && { [ -z "$_host" ] || [ "$_host" = "$_me" ]; } &&
        hx_same_proc "$_pid" "$_birth" && _d=$(hx_get "http://127.0.0.1:$_port$DESCRIPTOR" 2>/dev/null) &&
        [ -n "$_env_id" ] && [ "$(hx_json_str "$_d" environment_id)" = "$_env_id" ]; then
        echo "HX:reused=1"
        echo "HX:server=$_j"
        exit 0
    fi
fi

[ -x "$HX_BIN" ] || hx_fail "hx is not installed at $HX_BIN; run the install step (hx hosts upgrade) first"

[ -f "$LOG" ] && mv -f "$LOG" "$LOG.1"
rm -f "$SJ" # a dead server's record; the new server writes its own
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

_wait=${HX_START_WAIT:-30}
_limit=$((_wait * 4))
_i=0
_desc=""
while [ "$_i" -lt "$_limit" ]; do
    if ! hx_alive "$_pid"; then
        hx_fail "hx serve exited during startup" "$LOG" 80
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
    kill "$_pid" 2>/dev/null
    hx_fail "hx serve was not ready after ${_wait}s" "$LOG" 80
fi

_ver=$(hx_json_str "$_desc" hx_version)
_proto=$(hx_json_num "$_desc" protocol_version)
_birth=$(hx_pid_start "$_pid") # stop.sh signals only this exact process
printf '{"pid": %s, "port": %s, "managed": true, "hx_version": "%s", "protocol_version": %s, "hostname": "%s", "pid_start": "%s", "token": "%s"}\n' \
    "$_pid" "$_port" "$_ver" "${_proto:-0}" "$_me" "$_birth" "$HX_TOKEN" >"$SJ.tmp" && mv -f "$SJ.tmp" "$SJ" ||
    hx_fail "cannot write $SJ"
echo "HX:reused=0"
echo "HX:server=$(cat "$SJ")"
