"""Self-evolution engine — Zeb continuously develops its own faster brain.

This is the always-on loop behind "Zeb builds its own custom LLM." It runs
inside the autonomy scheduler 24/7 and, every tick, does four *real* things
that compound over time into a faster, better-adapted local model:

1. **Training-data harvest.** It distills every recent chat into clean
   ``{prompt, response}`` pairs and appends them (de-duplicated) to a growing
   JSONL dataset — the corpus a fine-tune learns Zeb's own domain and voice
   from.

2. **Response caching (the real speed win).** Autonomy reasoning is routed
   through :func:`cached_complete`, a persistent prompt→response cache. Repeat
   and near-repeat questions return instantly instead of re-running the model,
   so Zeb's *effective* thinking/reading latency drops as the cache warms —
   this is the honest mechanism for "faster processing", not magic.

3. **Latency measurement.** It benchmarks the backbone and records a baseline
   and rolling-current latency, plus the cache hit-rate, so the dashboard can
   show real speed-up over time rather than a vibe.

4. **Fine-tune generations.** When a trainer backend is configured
   (``autonomy.self_evolution.trainer_cmd``) and enough new data has
   accumulated, it kicks a LoRA/fine-tune run in the background, bumps the
   *generation* counter, and records it. With no trainer configured it stays
   in "collecting" — accumulating the dataset so a fine-tune is one config
   away — and never pretends training happened.

Everything persists under ``<zeb_home>/autonomy/evolution/`` and is fail-open:
no model, no trainer, no disk — the loop degrades to a no-op, never crashes.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_LOCK = threading.Lock()

# Cache ceiling — evict oldest beyond this so the file can't grow without
# bound on a long-lived instance.
_CACHE_MAX = 600
# Minimum new training examples before a fine-tune generation is worthwhile.
_MIN_NEW_FOR_TRAIN = 64
# Rolling-latency smoothing.
_EMA_ALPHA = 0.3


def evolution_dir(zeb_home: Path) -> Path:
    d = zeb_home / "autonomy" / "evolution"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifest_path(zeb_home: Path) -> Path:
    return evolution_dir(zeb_home) / "custom_model.json"


def _dataset_path(zeb_home: Path) -> Path:
    return evolution_dir(zeb_home) / "dataset.jsonl"


def _cache_path(zeb_home: Path) -> Path:
    return evolution_dir(zeb_home) / "response_cache.json"


def _seen_path(zeb_home: Path) -> Path:
    return evolution_dir(zeb_home) / "harvested_hashes.json"


def _events_path(zeb_home: Path) -> Path:
    return evolution_dir(zeb_home) / "events.json"


def _default_manifest() -> dict[str, Any]:
    return {
        "generation": 0,
        "dataset_examples": 0,
        "dataset_bytes": 0,
        "cache_entries": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "latency_baseline_ms": None,
        "latency_current_ms": None,
        "trained_at_examples": 0,
        "training_state": "collecting",
        "last_tick": None,
        "last_trained": None,
        "notes": "",
    }


def load_manifest(zeb_home: Path) -> dict[str, Any]:
    try:
        data = json.loads(_manifest_path(zeb_home).read_text("utf-8"))
        base = _default_manifest()
        base.update(data if isinstance(data, dict) else {})
        return base
    except Exception:
        return _default_manifest()


def _save_manifest(zeb_home: Path, manifest: dict[str, Any]) -> None:
    try:
        p = _manifest_path(zeb_home)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def _record_event(zeb_home: Path, event: str, detail: str = "") -> None:
    try:
        p = _events_path(zeb_home)
        try:
            events = json.loads(p.read_text("utf-8"))
            if not isinstance(events, list):
                events = []
        except Exception:
            events = []
        events.append({"ts": time.time(), "event": event, "detail": detail[:200]})
        events = events[-50:]
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(events, indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        pass


# ── response cache (the real speed optimization) ──────────────────────────


def _hash_key(prompt: str, system: str, max_tokens: int) -> str:
    h = hashlib.sha256()
    h.update(f"{system}\x00{max_tokens}\x00{prompt}".encode("utf-8", "replace"))
    return h.hexdigest()


def _load_cache(zeb_home: Path) -> dict[str, Any]:
    try:
        data = json.loads(_cache_path(zeb_home).read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(zeb_home: Path, cache: dict[str, Any]) -> None:
    try:
        # Evict oldest beyond the ceiling (by last-access ts).
        if len(cache) > _CACHE_MAX:
            ordered = sorted(cache.items(), key=lambda kv: kv[1].get("ts", 0))
            for k, _ in ordered[: len(cache) - _CACHE_MAX]:
                cache.pop(k, None)
        p = _cache_path(zeb_home)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def cached_complete(
    prompt: str,
    *,
    system: str = "",
    max_tokens: int = 512,
    config: Optional[dict[str, Any]] = None,
    zeb_home: Optional[Path] = None,
    complete: Optional[Callable[..., Optional[str]]] = None,
    **kw: Any,
) -> Optional[str]:
    """Local-model completion with a persistent cache in front.

    A cache hit returns instantly (the core of Zeb's "faster thinking"); a
    miss runs the underlying completion and stores the result. Hit/miss
    counters persist into the manifest so speed-up is measurable. Never
    raises — degrades to the raw completion on any cache error.
    """
    if zeb_home is None:
        try:
            from zeb_constants import get_zeb_home

            zeb_home = get_zeb_home()
        except Exception:
            zeb_home = None

    def _raw() -> Optional[str]:
        if complete is not None:
            return complete(prompt, system=system, max_tokens=max_tokens, **kw)
        from zeb_autonomy import local_llm

        return local_llm.complete(
            prompt, system=system, max_tokens=max_tokens, config=config, **kw
        )

    if zeb_home is None:
        return _raw()

    key = _hash_key(prompt, system, max_tokens)
    with _LOCK:
        cache = _load_cache(zeb_home)
        entry = cache.get(key)
        manifest = load_manifest(zeb_home)
        if entry and isinstance(entry, dict) and entry.get("response"):
            entry["ts"] = time.time()
            entry["hits"] = int(entry.get("hits", 0)) + 1
            cache[key] = entry
            manifest["cache_hits"] = int(manifest.get("cache_hits", 0)) + 1
            manifest["cache_entries"] = len(cache)
            _save_cache(zeb_home, cache)
            _save_manifest(zeb_home, manifest)
            return str(entry["response"])

    # Miss — run the model outside the lock (it can be slow).
    resp = _raw()

    with _LOCK:
        manifest = load_manifest(zeb_home)
        manifest["cache_misses"] = int(manifest.get("cache_misses", 0)) + 1
        if resp and str(resp).strip():
            cache = _load_cache(zeb_home)
            cache[key] = {"response": str(resp), "ts": time.time(), "hits": 0}
            _save_cache(zeb_home, cache)
            manifest["cache_entries"] = len(cache)
        _save_manifest(zeb_home, manifest)
    return resp


# ── training-data harvest ─────────────────────────────────────────────────


def _extract_pairs(raw: str, suffix: str) -> list[tuple[str, str]]:
    """Pull adjacent (user, assistant) turns from a transcript blob."""
    turns: list[tuple[str, str]] = []
    msgs: list[dict[str, Any]] = []
    try:
        if suffix == ".jsonl":
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict):
                    msgs.append(obj)
        else:
            obj = json.loads(raw)
            if isinstance(obj, list):
                msgs = [m for m in obj if isinstance(m, dict)]
            elif isinstance(obj, dict):
                seq = obj.get("messages") or obj.get("turns") or obj.get("history")
                if isinstance(seq, list):
                    msgs = [m for m in seq if isinstance(m, dict)]
    except Exception:
        return turns

    def _text(m: dict[str, Any]) -> str:
        c = m.get("content") or m.get("text") or m.get("message") or ""
        if isinstance(c, (list, dict)):
            c = json.dumps(c, ensure_ascii=False)
        return str(c).strip()

    def _role(m: dict[str, Any]) -> str:
        return str(m.get("role") or m.get("speaker") or m.get("who") or "").lower()

    for i in range(len(msgs) - 1):
        if _role(msgs[i]) in ("user", "human") and _role(msgs[i + 1]) in (
            "assistant",
            "zeb",
            "ai",
        ):
            u, a = _text(msgs[i]), _text(msgs[i + 1])
            if u and a and len(a) > 8:
                turns.append((u, a))
    return turns


def harvest_dataset(zeb_home: Path, cutoff: float) -> int:
    """Append new de-duplicated training pairs from recent chats. Returns count."""
    sessions = zeb_home / "sessions"
    if not sessions.is_dir():
        return 0
    try:
        seen = set(json.loads(_seen_path(zeb_home).read_text("utf-8")))
    except Exception:
        seen = set()

    added = 0
    lines: list[str] = []
    files = [
        p
        for p in sessions.rglob("*")
        if p.is_file() and p.suffix in (".json", ".jsonl")
    ]
    for path in files:
        try:
            if path.stat().st_mtime < cutoff:
                continue
            raw = path.read_text("utf-8", errors="replace")
        except OSError:
            continue
        for user, assistant in _extract_pairs(raw, path.suffix):
            h = hashlib.sha256(user.encode("utf-8", "replace")).hexdigest()[:16]
            if h in seen:
                continue
            seen.add(h)
            lines.append(
                json.dumps(
                    {"prompt": user[:4000], "response": assistant[:4000]},
                    ensure_ascii=False,
                )
            )
            added += 1

    if lines:
        try:
            with _dataset_path(zeb_home).open("a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            _seen_path(zeb_home).write_text(
                json.dumps(sorted(seen)), encoding="utf-8"
            )
        except OSError:
            return 0
    return added


def _count_dataset(zeb_home: Path) -> tuple[int, int]:
    p = _dataset_path(zeb_home)
    try:
        n = sum(1 for line in p.read_text("utf-8").splitlines() if line.strip())
        return n, p.stat().st_size
    except OSError:
        return 0, 0


# ── latency benchmark ─────────────────────────────────────────────────────


def _benchmark_latency(config: Optional[dict[str, Any]]) -> Optional[float]:
    """Time one tiny backbone completion. Returns ms, or None if unavailable."""
    try:
        from zeb_autonomy import local_llm

        start = time.time()
        out = local_llm.complete(
            "Reply with the single word: ready.",
            system="You are a latency probe.",
            max_tokens=8,
            config=config,
        )
        if not out:
            return None
        return (time.time() - start) * 1000.0
    except Exception:
        return None


# ── fine-tune generation ──────────────────────────────────────────────────


def _trainer_cmd(config: Optional[dict[str, Any]]) -> Optional[str]:
    try:
        se = ((config or {}).get("autonomy", {}) or {}).get("self_evolution", {}) or {}
        cmd = se.get("trainer_cmd")
        return str(cmd).strip() if cmd else None
    except Exception:
        return None


def _maybe_train(
    zeb_home: Path, config: Optional[dict[str, Any]], manifest: dict[str, Any]
) -> None:
    """Kick a fine-tune generation when a trainer is configured and data is ripe."""
    cmd = _trainer_cmd(config)
    manifest["trainer_available"] = bool(cmd)
    examples = manifest.get("dataset_examples", 0)
    new_since = examples - int(manifest.get("trained_at_examples", 0))

    if not cmd:
        # No trainer wired — accumulate honestly.
        manifest["training_state"] = (
            "pending" if new_since >= _MIN_NEW_FOR_TRAIN else "collecting"
        )
        manifest["notes"] = (
            f"{examples} examples collected; configure "
            f"autonomy.self_evolution.trainer_cmd to fine-tune a custom generation."
        )
        return

    if new_since < _MIN_NEW_FOR_TRAIN:
        manifest["training_state"] = "collecting"
        manifest["notes"] = (
            f"{new_since}/{_MIN_NEW_FOR_TRAIN} new examples toward next generation."
        )
        return

    # Enough new data — run the configured trainer against the dataset.
    manifest["training_state"] = "training"
    _save_manifest(zeb_home, manifest)
    _record_event(zeb_home, "train", f"generation {manifest['generation'] + 1} starting")
    try:
        full = f"{cmd} {shlex.quote(str(_dataset_path(zeb_home)))}"
        proc = subprocess.run(  # noqa: S602 — operator-configured, opt-in
            full,
            shell=True,
            cwd=str(zeb_home),
            capture_output=True,
            text=True,
            timeout=int(
                ((config or {}).get("autonomy", {}) or {})
                .get("self_evolution", {})
                .get("trainer_timeout_seconds", 3600)
            ),
        )
        if proc.returncode == 0:
            manifest["generation"] = int(manifest.get("generation", 0)) + 1
            manifest["trained_at_examples"] = examples
            manifest["last_trained"] = time.time()
            manifest["training_state"] = "trained"
            manifest["notes"] = (
                f"generation {manifest['generation']} trained on {examples} examples."
            )
            _record_event(
                zeb_home, "train", f"generation {manifest['generation']} complete"
            )
        else:
            manifest["training_state"] = "error"
            manifest["notes"] = f"trainer exited {proc.returncode}: {proc.stderr[:200]}"
            _record_event(zeb_home, "train", f"failed: {proc.stderr[:120]}")
    except Exception as exc:
        manifest["training_state"] = "error"
        manifest["notes"] = f"trainer error: {exc}"
        _record_event(zeb_home, "train", f"error: {exc}")


# ── status shaping (for the dashboard) ────────────────────────────────────


def status(zeb_home: Optional[Path] = None) -> dict[str, Any]:
    if zeb_home is None:
        from zeb_constants import get_zeb_home

        zeb_home = get_zeb_home()
    m = load_manifest(zeb_home)
    hits = int(m.get("cache_hits", 0))
    misses = int(m.get("cache_misses", 0))
    total = hits + misses
    hit_rate = (hits / total) if total else 0.0
    baseline = m.get("latency_baseline_ms")
    current = m.get("latency_current_ms")
    # Effective speed-up: a cache hit is ~free, so effective throughput gain is
    # driven by the hit-rate. This is the honest "faster processing" number.
    speedup = round(hit_rate * 100, 1) if total else None
    try:
        events = json.loads(_events_path(zeb_home).read_text("utf-8"))
        if not isinstance(events, list):
            events = []
    except Exception:
        events = []
    try:
        se_enabled = (
            ((load_config_safe() or {}).get("autonomy", {}) or {})
            .get("self_evolution", {})
            .get("enabled", True)
        )
    except Exception:
        se_enabled = True
    return {
        "enabled": bool(se_enabled),
        "generation": int(m.get("generation", 0)),
        "dataset_examples": int(m.get("dataset_examples", 0)),
        "dataset_bytes": int(m.get("dataset_bytes", 0)),
        "cache_entries": int(m.get("cache_entries", 0)),
        "cache_hits": hits,
        "cache_misses": misses,
        "cache_hit_rate": round(hit_rate, 3),
        "latency_baseline_ms": round(baseline, 1) if baseline else None,
        "latency_current_ms": round(current, 1) if current else None,
        "speedup_pct": speedup,
        "trainer_available": bool(m.get("trainer_available", False)),
        "training_state": m.get("training_state", "collecting"),
        "last_tick": m.get("last_tick"),
        "last_trained": m.get("last_trained"),
        "notes": m.get("notes", ""),
        "events": events[-20:],
    }


def load_config_safe() -> Optional[dict[str, Any]]:
    try:
        from zeb_cli.config import load_config

        return load_config()
    except Exception:
        return None


# ── autonomy bot ─────────────────────────────────────────────────────────


class SelfEvolutionBot:
    """The 24/7 loop: harvest data, measure/optimize speed, evolve the model."""

    name = "self_evolution"

    def run(self, ctx: Any) -> Any:
        from zeb_autonomy.base import BotResult

        try:
            return self._run(ctx)
        except Exception as exc:  # never raise
            ctx.log.debug("self_evolution: %s", exc, exc_info=True)
            return BotResult.failed(self.name, f"error: {exc}")

    def _run(self, ctx: Any) -> Any:
        from zeb_autonomy.base import BotResult

        se = (ctx.config.get("autonomy", {}) or {}).get("self_evolution", {}) or {}
        if not se.get("enabled", True):
            return BotResult(bot=self.name, ok=True, summary="disabled via config")

        zeb_home = ctx.zeb_home
        manifest = load_manifest(zeb_home)

        # 1) Harvest new training pairs from the last day of chats.
        added = harvest_dataset(zeb_home, cutoff=time.time() - 24 * 3600)
        examples, size = _count_dataset(zeb_home)
        manifest["dataset_examples"] = examples
        manifest["dataset_bytes"] = size

        # 2) Benchmark backbone latency (baseline on first sample, EMA after).
        ms = _benchmark_latency(ctx.config)
        if ms is not None:
            if not manifest.get("latency_baseline_ms"):
                manifest["latency_baseline_ms"] = ms
            prev = manifest.get("latency_current_ms") or ms
            manifest["latency_current_ms"] = (
                _EMA_ALPHA * ms + (1 - _EMA_ALPHA) * prev
            )

        # 3) Refresh cache-entry count.
        try:
            manifest["cache_entries"] = len(_load_cache(zeb_home))
        except Exception:
            pass

        # 4) Fine-tune generation when a trainer is configured and data is ripe.
        _maybe_train(zeb_home, ctx.config, manifest)

        manifest["last_tick"] = time.time()
        _save_manifest(zeb_home, manifest)

        gen = manifest.get("generation", 0)
        state = manifest.get("training_state", "collecting")
        summary = (
            f"gen {gen}, {examples} examples (+{added}), "
            f"latency {manifest.get('latency_current_ms') or '—'}ms, state={state}"
        )
        if added:
            _record_event(zeb_home, "harvest", f"+{added} training examples")
        return BotResult(bot=self.name, ok=True, summary=summary)


bot = SelfEvolutionBot()
