"""Download pinned public ONNX weights; never runs inference."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MODEL = "Xenova/all-MiniLM-L6-v2"
REVISION = "751bff37182d3f1213fa05d7196b954e230abad9"
COMMON = ["config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]
WEIGHTS = {"fp32": "onnx/model.onnx", "fp16": "onnx/model_fp16.onnx", "q8": "onnx/model_quantized.onnx"}
EXPECTED = {
    "onnx/model.onnx": (90387606, "759c3cd2b7fe7e93933ad23c4c9181b7396442a2ed746ec7c1d46192c469c46e"),
    "onnx/model_fp16.onnx": (45297825, "2cdb5e58291813b6d6e248ed69010100246821a367fa17b1b81ae9483744533d"),
    "onnx/model_quantized.onnx": (22972370, "afdb6f1a0e45b715d0bb9b11772f032c399babd23bfc31fed1c170afc848bdb1"),
}

def download(url, target, size=None):
    temporary = target.with_suffix(target.suffix + ".part")
    if size is None:
        with urllib.request.urlopen(url, timeout=180) as response, temporary.open("wb") as out:
            while block := response.read(1024 * 1024):
                out.write(block)
    else:
        with temporary.open("wb") as out:
            out.truncate(size)
        def part(start):
            end = min(size, start + 4 * 1024 * 1024) - 1
            for attempt in range(3):
                try:
                    request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
                    with urllib.request.urlopen(request, timeout=180) as response:
                        if response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {start}-{end}/"):
                            raise RuntimeError("Model host did not honor the requested byte range")
                        data = response.read()
                    if len(data) != end - start + 1:
                        raise RuntimeError("Incomplete model download")
                    with temporary.open("r+b") as out:
                        out.seek(start)
                        out.write(data)
                    return
                except Exception:
                    if attempt == 2:
                        raise
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(part, range(0, size, 4 * 1024 * 1024)))
    temporary.replace(target)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1] / "public/models"))
    args = parser.parse_args()
    root = Path(args.root)
    records = []
    for name in COMMON + list(WEIGHTS.values()):
        target = root / MODEL / name
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}"
        if not target.exists():
            print(f"Downloading {name}", flush=True)
            download(url, target, EXPECTED.get(name, (None,))[0])
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if name in EXPECTED and (target.stat().st_size, digest) != EXPECTED[name]:
            raise RuntimeError(f"Integrity check failed for {target}; remove it and download again")
        records.append({"file": name, "bytes": target.stat().st_size, "sha256": digest, "url": url})
    common_bytes = sum(r["bytes"] for r in records if r["file"] in COMMON)
    sizes = {dtype: common_bytes + next(r["bytes"] for r in records if r["file"] == name)
             for dtype, name in WEIGHTS.items()}
    manifest = {"model": MODEL, "revision": REVISION, "dimension": 384,
                "license": "Apache-2.0", "files": records, "totalBytesByDtype": sizes,
                "compression": {dtype: sizes["fp32"] / size for dtype, size in sizes.items()}}
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"bytes": sizes, "compression": manifest["compression"]}, indent=2))

if __name__ == "__main__":
    main()
