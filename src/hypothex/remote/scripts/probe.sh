# probe: report OS, arch, Python >= 3.11, uv, GPU count, SLURM, and the home path.
# Inputs: HX_HOME.
hx_expand_home
echo "HX:os=$(uname -s | tr '[:upper:]' '[:lower:]')"
echo "HX:arch=$(uname -m)"
echo "HX:home=$HX_HOME"

_py=""
for _c in python3.13 python3.12 python3.11 python3; do
    if command -v "$_c" >/dev/null 2>&1; then
        _v=$("$_c" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null) || continue
        case $_v in
            3.1[1-9].* | 3.[2-9][0-9].*)
                _py=$_v
                break
                ;;
        esac
    fi
done
echo "HX:python=$_py"

_uv=""
if _uvbin=$(hx_find_uv); then
    _uv=$("$_uvbin" --version 2>/dev/null | sed -n 's/^uv \([^ ]*\).*/\1/p')
fi
echo "HX:uv=$_uv"

_gpus=0
if command -v nvidia-smi >/dev/null 2>&1; then
    _gpus=$(nvidia-smi -L 2>/dev/null | grep -c '^GPU ' || true)
fi
echo "HX:gpus=${_gpus:-0}"

_slurm=""
if command -v sbatch >/dev/null 2>&1; then
    _slurm=$(sbatch --version 2>/dev/null | sed -n 's/^slurm[^0-9]*\([0-9][^ ]*\).*/\1/p')
fi
echo "HX:slurm=$_slurm"
