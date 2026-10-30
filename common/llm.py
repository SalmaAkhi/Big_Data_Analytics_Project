"""Minimal Gemini REST client: JSON generation, embeddings, disk cache, retries, token accounting."""
import hashlib
import json
import random
import time

import requests

from common import config

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
RETRY_STATUS = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


def _post(model, method, body, timeout=120, max_tries=6):
    url = f"{BASE}/{model}:{method}"
    headers = {"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"}
    last = None
    for attempt in range(max_tries):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=timeout)
        except requests.RequestException as e:
            last = str(e)
        else:
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code not in RETRY_STATUS:
                raise LLMError(last)
        time.sleep(min(60, 2 ** attempt + random.random()))
    raise LLMError(last)


def _cache_path(key):
    return config.CACHE / (hashlib.sha256(key.encode("utf-8")).hexdigest()[:32] + ".json")


def generate(prompt, system=None, schema=None, temperature=0.0, use_cache=True):
    """Return dict(text, data, model, input_tokens, output_tokens, latency_s, cached)."""
    gen_cfg = {"temperature": temperature}
    if schema is not None:
        gen_cfg["responseMimeType"] = "application/json"
        gen_cfg["responseSchema"] = schema
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen_cfg}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    key = json.dumps([config.GEMINI_MODELS, body], sort_keys=True)
    cp = _cache_path(key)
    if use_cache and cp.exists():
        out = json.loads(cp.read_text(encoding="utf-8"))
        out["cached"] = True
        return out

    errors = []
    for model in config.GEMINI_MODELS:
        t0 = time.time()
        try:
            resp = _post(model, "generateContent", body)
        except LLMError as e:
            errors.append(f"{model}: {e}")
            continue
        latency = time.time() - t0
        cand = (resp.get("candidates") or [{}])[0]
        parts = cand.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        usage = resp.get("usageMetadata", {})
        out = {
            "text": text,
            "data": None,
            "model": model,
            "input_tokens": usage.get("promptTokenCount", 0),
            "output_tokens": usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
            "latency_s": round(latency, 3),
            "cached": False,
        }
        if schema is not None:
            out["data"] = parse_json(text)
        cp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return out
    raise LLMError("All models failed: " + " | ".join(errors))


def parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1:] if "\n" in text else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


_local_model = None


def embed(texts, task_type="RETRIEVAL_DOCUMENT", batch_size=50):
    """Embed a list of texts, returns list of vectors (EMBED_DIM).

    Default backend is a local ONNX model (BAAI/bge-small-en-v1.5 via fastembed): no quota, no cost.
    Set EMBED_BACKEND=gemini to use gemini-embedding-001 instead (free tier is limited to ~100 texts/min).
    """
    global _local_model
    if config.EMBED_BACKEND == "local":
        if _local_model is None:
            from fastembed import TextEmbedding
            _local_model = TextEmbedding(config.LOCAL_EMBED_MODEL, cache_dir=str(config.CACHE / "fastembed"))
        if task_type == "RETRIEVAL_QUERY":  # BGE query instruction
            texts = [f"Represent this sentence for searching relevant passages: {t}" for t in texts]
        return [v.tolist() for v in _local_model.embed(texts, batch_size=batch_size)]

    model = config.GEMINI_EMBED_MODEL
    vectors = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        body = {"requests": [{
            "model": f"models/{model}",
            "content": {"parts": [{"text": t[:2000]}]},
            "taskType": task_type,
            "outputDimensionality": config.EMBED_DIM,
        } for t in chunk]}
        resp = _post(model, "batchEmbedContents", body, max_tries=8)
        vectors.extend(e["values"] for e in resp["embeddings"])
    return vectors


def cost_usd(input_tokens, output_tokens):
    return input_tokens / 1e6 * config.PRICE_INPUT_PER_M + output_tokens / 1e6 * config.PRICE_OUTPUT_PER_M
