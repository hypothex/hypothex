# logs: print the last HX_LINES lines of <home>/serve/server.log.
# Inputs: HX_HOME, HX_LINES.
hx_expand_home
LOG=$HX_HOME/serve/server.log
[ -f "$LOG" ] || hx_fail "no server log at $LOG"
tail -n "$HX_LINES" "$LOG" | sed 's/^/HX:log=/'
