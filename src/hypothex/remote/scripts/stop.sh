# stop: stop the env server in <home>/serve/server.json if Hypothex started it
# (managed). External servers are left alone. The pid is signalled only when the
# record names this host and the process has the recorded birth (pid_start): a
# shared home seen from another login node, or a pid the OS gave to another
# process after the server died, is never signalled. Inputs: HX_HOME.
hx_expand_home
SERVE=$HX_HOME/serve
SJ=$SERVE/server.json

[ -d "$SERVE" ] || { echo "HX:stopped=0"; echo "HX:reason=no server"; exit 0; }
hx_lock "$SERVE/.lock"
if [ ! -f "$SJ" ]; then
    echo "HX:stopped=0"
    echo "HX:reason=no server"
    exit 0
fi
_j=$(tr -d '\n' <"$SJ")
case $_j in
    *'"managed": true'* | *'"managed":true'*) ;;
    *)
        echo "HX:stopped=0"
        echo "HX:reason=external"
        exit 0
        ;;
esac
_pid=$(hx_json_num "$_j" pid)
_host=$(hx_json_str "$_j" hostname)
_birth=$(hx_json_str "$_j" pid_start)
_me=$(hostname 2>/dev/null || echo unknown)
if [ "$_host" != "$_me" ]; then
    echo "HX:stopped=0"
    echo "HX:reason=server runs on ${_host:-an unknown host}, not $_me"
    exit 0
fi
if [ -z "$_birth" ]; then
    echo "HX:stopped=0"
    echo "HX:reason=server.json has no pid_start; cannot tell the server from a recycled pid"
    exit 0
fi
if [ -n "$_pid" ]; then
    hx_stop_pid "$_pid" "$_birth"
fi
rm -f "$SJ"
echo "HX:stopped=1"
