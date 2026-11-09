"""Download and verify the official PP-OCRv6 Small ONNX models."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

MODEL_ROOT = Path(__file__).resolve().parents[1] / ".cache" / "paddlex" / "onnx_models"
MODELS = {
    "PP-OCRv6_small_det": (
        "28fe5895c24f",
        {
            "inference.onnx": "d73e0058b7a8086bbd57f3d10b8bcd4ff95363f67e06e2762b5e814fe9c9410e",
            "inference.yml": "193f435274bf9f0b5f71a929bbfbcf148282df7e633b34e7c373e8f44741b516",
        },
    ),
    "PP-OCRv6_small_rec": (
        "b8f84f0b80c5",
        {
            "inference.onnx": "5435fd747c9e0efe15a96d0b378d5bd157e9492ed8fd80edf08f30d02fa24634",
            "inference.yml": "ab078671bb49f06228eadccd34f1bb501e157f7a047095ffb943ba81512c77d1",
        },
    ),
}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(target: Path, checksum: str, sources: dict[str, str]) -> None:
    if target.is_file() and sha256(target) == checksum:
        print(f"Verified {target.parent.name}/{target.name}", flush=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    for name, url in sources.items():
        print(f"Downloading {target.parent.name}/{target.name} from {name}", flush=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as temp:
            temporary = Path(temp.name)
        try:
            request = Request(url, headers={"User-Agent": "ScreenTranslateAssistant/0.1"})
            with urlopen(request, timeout=20) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output, length=256 * 1024)
            if sha256(temporary) != checksum:
                raise ValueError("SHA-256 mismatch")
            temporary.replace(target)
            return
        except (OSError, ValueError) as error:
            print(f"{name}: {error}", flush=True)
        finally:
            temporary.unlink(missing_ok=True)
    raise RuntimeError(f"Could not download a verified copy of {target.parent.name}/{target.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("auto", "modelscope", "huggingface"), default="auto")
    args = parser.parse_args()
    for model, (revision, files) in MODELS.items():
        repository = f"PaddlePaddle/{model}_onnx"
        for filename, checksum in files.items():
            sources = {
                "modelscope": (
                    f"https://www.modelscope.cn/api/v1/models/{repository}/repo"
                    f"?Revision=master&FilePath={filename}"
                ),
                "huggingface": f"https://huggingface.co/{repository}/resolve/{revision}/{filename}",
            }
            if args.source != "auto":
                sources = {args.source: sources[args.source]}
            download(MODEL_ROOT / model / filename, checksum, sources)


if __name__ == "__main__":
    main()
