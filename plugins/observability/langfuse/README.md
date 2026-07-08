# Langfuse Observability Plugin

This plugin ships bundled with Zeb but is **opt-in** — it only loads when
you explicitly enable it.

## Enable

Pick one:

```bash
# Interactive: walks you through credentials + SDK install + enable
zeb tools  # → Langfuse Observability

# Manual
pip install langfuse
zeb plugins enable observability/langfuse
```

## Required credentials

Set these in `~/.zeb/.env` (or via `zeb tools`):

```bash
ZEB_LANGFUSE_PUBLIC_KEY=pk-lf-...
ZEB_LANGFUSE_SECRET_KEY=sk-lf-...
ZEB_LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

Without the SDK or credentials the hooks no-op silently — the plugin fails
open.

## Verify

```bash
zeb plugins list                 # observability/langfuse should show "enabled"
zeb chat -q "hello"              # then check Langfuse for a "Zeb turn" trace
```

## Optional tuning

```bash
ZEB_LANGFUSE_ENV=production       # environment tag
ZEB_LANGFUSE_RELEASE=v1.0.0       # release tag
ZEB_LANGFUSE_SAMPLE_RATE=0.5      # sample 50% of traces
ZEB_LANGFUSE_MAX_CHARS=12000      # max chars per field (default: 12000)
ZEB_LANGFUSE_DEBUG=true           # verbose plugin logging
```

## Disable

```bash
zeb plugins disable observability/langfuse
```
