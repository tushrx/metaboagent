#!/usr/bin/env python3
"""
MetaboAgent — Pre-flight Check
Run this FIRST at 10 AM to verify everything is ready.
Usage: python scripts/preflight.py
"""
import sys
import subprocess
import importlib


def check(name: str, fn):
    """Run a check function and print result."""
    try:
        result = fn()
        print(f"  ✓ {name}: {result}")
        return True
    except Exception as e:
        print(f"  ✗ {name}: {e}")
        return False


def check_python_version():
    v = sys.version_info
    assert v.major == 3 and v.minor >= 10, f"Need Python 3.10+, got {v.major}.{v.minor}"
    return f"Python {v.major}.{v.minor}.{v.micro}"


def check_gpu():
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        capture_output=True, text=True, timeout=10,
    )
    gpus = result.stdout.strip().split("\n")
    assert len(gpus) >= 4, f"Expected 4 GPUs, found {len(gpus)}"
    return f"{len(gpus)} GPUs detected"


def _primary_llm_base_url() -> str:
    """Resolve via config.py so env overrides (PRIMARY_LLM_BASE_URL) apply."""
    from config import PRIMARY_LLM_BASE_URL
    return PRIMARY_LLM_BASE_URL.rstrip("/")


def check_vllm():
    import requests
    base = _primary_llm_base_url()
    resp = requests.get(f"{base}/models", timeout=10)
    assert resp.status_code == 200, f"vLLM returned {resp.status_code}"
    models = resp.json()
    model_ids = [m["id"] for m in models.get("data", [])]
    return f"Models available at {base}: {model_ids}"


def check_vllm_inference():
    import requests
    base = _primary_llm_base_url()
    resp = requests.post(
        f"{base}/chat/completions",
        json={
            "model": resp_model_id(),
            "messages": [{"role": "user", "content": "What is the EC number for alcohol dehydrogenase? Reply in one line."}],
            "max_tokens": 100,
            "temperature": 0.1,
        },
        timeout=60,
    )
    assert resp.status_code == 200, f"Inference failed: {resp.status_code}"
    answer = resp.json()["choices"][0]["message"]["content"]
    return f"Gemma responds: {answer[:80]}..."


def resp_model_id():
    import requests
    resp = requests.get(f"{_primary_llm_base_url()}/models", timeout=10)
    return resp.json()["data"][0]["id"]


def check_kegg_api():
    import requests
    resp = requests.get("https://rest.kegg.jp/info/kegg", timeout=15)
    assert resp.status_code == 200, f"KEGG returned {resp.status_code}"
    return "KEGG REST API reachable"


def check_pubmed_api():
    import requests
    resp = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi?db=pubmed&retmode=json",
        timeout=15,
    )
    assert resp.status_code == 200, f"PubMed returned {resp.status_code}"
    return "PubMed E-utilities reachable"


def check_disk_space():
    # Check the volume that actually holds DATA_ROOT so a migration to
    # /mnt/storage_sdd is reflected here instead of always probing /home.
    from config import DATA_ROOT
    target = str(DATA_ROOT)
    result = subprocess.run(["df", "-h", target], capture_output=True, text=True)
    lines = result.stdout.strip().split("\n")
    if len(lines) >= 2:
        parts = lines[-1].split()
        avail = parts[3] if len(parts) >= 4 else "unknown"
        return f"{avail} available on {target}"
    return "Could not determine"


def check_ram():
    result = subprocess.run(["free", "-h"], capture_output=True, text=True)
    lines = result.stdout.strip().split("\n")
    if len(lines) >= 2:
        parts = lines[1].split()
        total = parts[1] if len(parts) >= 2 else "unknown"
        avail = parts[6] if len(parts) >= 7 else "unknown"
        return f"Total: {total}, Available: {avail}"
    return "Could not determine"


def check_package(pkg_name: str, import_name: str = None):
    """Check if a Python package is importable."""
    def _check():
        mod = importlib.import_module(import_name or pkg_name)
        version = getattr(mod, "__version__", "installed")
        return f"v{version}"
    return _check


def main():
    print("\n" + "=" * 60)
    print("  MetaboAgent — Pre-flight System Check")
    print("=" * 60)

    all_ok = True

    print("\n🖥  System:")
    all_ok &= check("Python version", check_python_version)
    all_ok &= check("RAM", check_ram)
    all_ok &= check("Disk space", check_disk_space)
    all_ok &= check("GPUs", check_gpu)

    print("\n🤖 LLM Inference:")
    all_ok &= check("vLLM server", check_vllm)
    all_ok &= check("Gemma 4 inference", check_vllm_inference)

    print("\n🌐 External APIs:")
    all_ok &= check("KEGG REST API", check_kegg_api)
    all_ok &= check("PubMed E-utilities", check_pubmed_api)

    print("\n📦 Python Packages:")
    packages = [
        ("langchain", "langchain"),
        ("langchain-openai", "langchain_openai"),
        ("chromadb", "chromadb"),
        ("transformers", "transformers"),
        ("torch", "torch"),
        ("sentence-transformers", "sentence_transformers"),
        ("gradio", "gradio"),
        ("biopython", "Bio"),
        ("pydantic", "pydantic"),
        ("requests", "requests"),
        ("rich", "rich"),
    ]
    for pkg_name, import_name in packages:
        all_ok &= check(pkg_name, check_package(import_name))

    print("\n" + "=" * 60)
    if all_ok:
        print("  ✅ ALL CHECKS PASSED — Ready to build MetaboAgent!")
    else:
        print("  ⚠️  Some checks failed — fix issues above before starting")
        print("  Tip: pip install -r requirements.txt --break-system-packages")
    print("=" * 60 + "\n")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
