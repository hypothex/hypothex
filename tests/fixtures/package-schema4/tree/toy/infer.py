import json
import os
import sys
from pathlib import Path

run_dir = Path(os.environ["HYPOTHEX_RUN_DIR"])
ckpt = sys.argv[sys.argv.index("--ckpt") + 1]
with (run_dir / "predictions" / "predictions.jsonl").open("w") as fh:
    for i in range(4):
        fh.write(json.dumps({"id": f"ex-{i}", "prediction": i % 2}) + "\n")
print("inferred with", ckpt)
