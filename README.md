# AdevX

A practical starter chatbot that can handle many tasks with tools.

It includes:
- Chat loop with memory
- Interactive "AdevX is thinking..." waiting animation
- Multi-mode assistant: chat, coding, image, research, and agent
- Optional online tool-calling mode with:
  - OpenAI (`OPENAI_API_KEY`)
  - OpenRouter (`OPENROUTER_API_KEY`, supports `openrouter/free`)
  - Groq (`GROQ_API_KEY`)
  - Together (`TOGETHER_API_KEY`)
  - Ollama local (`ollama-local`, no cloud key needed)
- Offline local minimal-reasoning mode (no API key required)
- Automatic provider failover chain (smart routing + fallback)
- Phase 2 RAG: project indexing + retrieval context injection
- Modular runtime RAG: incremental semantic indexing + hybrid retrieval
  (BM25 lexical + sparse semantic similarity + symbol boosts)
- Built-in tools for:
  - file listing/reading/writing/appending/searching
  - safe math calculation
  - image metadata analysis (PNG/JPG/GIF/BMP/WEBP)
  - URL fetching
  - shell command execution (interactive approval)
  - text summarization

## Quick Start

```powershell
python taskbot.py
```

Modular architecture preview runtime:

```powershell
python -m adevx.main
```

The modular runtime now uses live provider calls (OpenAI-compatible HTTP APIs)
instead of scaffold echo responses, with retry + circuit-breaker routing.
It also runs background incremental index refresh for workspace retrieval quality.

Autonomous reasoning docs:

- `docs/ARCHITECTURE_REPORT.md`
- `docs/AUTONOMOUS_ENGINE.md`

## Online Mode Setup

Use one provider key, then run AdevX.

OpenAI:

```powershell
$env:OPENAI_API_KEY="your_key"
python taskbot.py --provider openai --model gpt-4.1-mini
```

OpenRouter (free router):

```powershell
$env:OPENROUTER_API_KEY="your_key"
python taskbot.py --provider openrouter --model openrouter/free
```

Groq (free plan, rate-limited):

```powershell
$env:GROQ_API_KEY="your_key"
python taskbot.py --provider groq
```

Together AI:

```powershell
$env:TOGETHER_API_KEY="your_key"
python taskbot.py --provider together
```

Ollama local (fully offline):

```powershell
ollama pull qwen2.5:7b
python taskbot.py --provider ollama-local --model qwen2.5:7b
```

## Smart Routing + Fallback

- Default chain: `openai -> groq -> openrouter -> together`
- Add local LLM fallback to chain manually if you want:
  - `openai,groq,openrouter,together,ollama-local`
- If one provider fails, AdevX automatically tries the next provider.
- Configure chain:

```powershell
$env:ADEVX_PROVIDER_CHAIN="openrouter,groq,together,ollama-local"
```

- Disable smart routing:

```powershell
$env:ADEVX_SMART_ROUTING="0"
```

## Offline Commands

Slash commands always work (even while online):

- `/h`
- `/help`
- `/remember <note>`
- `/memory`
- `/forget`
- `/about`
- `/models`
- `/use provider:model`
- `/autotune [max_latency_seconds]`
- `/speed fast|balanced|quality`
- `/health [timeout_seconds]`
- `/modes`
- `/mode <name>`
- `/image <path>`
- `/rag status|rebuild|query <text>|on|off`
- `/phase run|status`
- `/status`
- `/online`
- `/offline`
- `/ls [path]`
- `/read <path>`
- `/write <path> <content>`
- `/append <path> <content>`
- `/search <query> [path]`
- `/calc <expression>`
- `/fetch <url>`
- `/shell <command>`
- `/summarize <text>`
- `/exit`

## Offline Natural Language (No API)

In offline mode, AdevX also supports simple plain-text tasks like:

- `create a file named hello.txt with text: hi`
- `read hello.txt`
- `list files`
- `calculate sqrt(144) + 6`
- `search hello in .`
- `summarize <your text>`
- `remember my project is BChat`

Model switch examples:

- `/models`
- `/use groq:llama-3.1-8b-instant`
- `/use openrouter:openrouter/free`
- `/use ollama-local:qwen2.5:7b`
- `/autotune 15`
- `/speed fast`
- `/mode coding`
- `/mode image`
- `/image assets/logo.png`
- `/rag rebuild`
- `/rag query merge sort implementation`
- `/phase run`

Phase automation:

```text
/phase run
/phase status
```

`/phase run` currently automates:
- RAG rebuild
- local model autotune (if available)
- speed profile optimization
- capability benchmark scoring (internal heuristic)

RAG quick start:

```text
/rag rebuild
/rag status
/rag query auth middleware
```

## One-shot mode

```powershell
python taskbot.py --once "/calc sqrt(144) + 6"
```

Disable animation in interactive mode:

```powershell
python taskbot.py --no-animation
```

For slow local models, increase local timeout:

```powershell
$env:ADEVX_OLLAMA_TIMEOUT="240"
```

## Tests

Run core regression tests:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## Notes

- This bot is a strong foundation, but no system can literally do "any task" without limits.
- Quality depends heavily on the model/provider you choose.
- In offline mode, default behavior is rule-based (no cloud token billing).
- If Ollama is running locally, offline mode can also use a local LLM for broader reasoning.
- File operations are restricted to the current workspace for safety.
- Shell commands always require your approval before running.

## Author

Aditya Pal
