# install: put a wheel under <home>/runtime with `uv tool install --force`.
# Inputs: HX_HOME, HX_STEP (prepare | install), and for install HX_WHEEL
# (final wheel file name) and HX_UPLOAD (temporary name the hub copied to).
hx_expand_home
RT=$HX_HOME/runtime
UV_INSTALLER_URL=https://astral.sh/uv/install.sh

mkdir -p "$RT/wheels" || hx_fail "cannot create $RT/wheels"
if [ "$HX_STEP" = "prepare" ]; then
    echo "HX:home=$HX_HOME"
    exit 0
fi

hx_install_uv() {
    : >"$RT/uv-install.log"
    if command -v curl >/dev/null 2>&1; then
        _fetch="curl -LsSf $UV_INSTALLER_URL"
    elif command -v wget >/dev/null 2>&1; then
        _fetch="wget -qO- $UV_INSTALLER_URL"
    else
        hx_fail "uv is missing on the host and neither curl nor wget is available to install it; install uv (https://docs.astral.sh/uv/) on the host and retry"
    fi
    $_fetch 2>>"$RT/uv-install.log" |
        env UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 \
            sh >>"$RT/uv-install.log" 2>&1
    hx_find_uv >/dev/null ||
        hx_fail "uv is missing on the host and the installer from $UV_INSTALLER_URL failed (no network?); install uv (https://docs.astral.sh/uv/) on the host and retry" "$RT/uv-install.log" 20
}

hx_lock "$RT/.lock"
[ -f "$RT/wheels/$HX_UPLOAD" ] || hx_fail "uploaded wheel $RT/wheels/$HX_UPLOAD is missing"
mv -f "$RT/wheels/$HX_UPLOAD" "$RT/wheels/$HX_WHEEL" || hx_fail "cannot move the wheel into $RT/wheels"

if ! UV=$(hx_find_uv); then
    hx_install_uv
    UV=$(hx_find_uv)
fi
echo "HX:uv=$UV"

UV_TOOL_DIR="$RT/tools" UV_TOOL_BIN_DIR="$RT/bin" \
    "$UV" tool install --force "$RT/wheels/$HX_WHEEL" >"$RT/install.log" 2>&1 ||
    hx_fail "uv tool install failed for $HX_WHEEL" "$RT/install.log" 40
_ver=$("$RT/bin/hx" --version 2>>"$RT/install.log") ||
    hx_fail "installed hx at $RT/bin/hx does not run" "$RT/install.log" 40
echo "HX:installed=$_ver"
