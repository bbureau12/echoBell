# Vicuna Setup Guide for echoBell

## Overview

This guide helps you set up Vicuna (a local LLM) for echoBell's conversational doorbell features.

## Why Vicuna?

- ✅ **Self-hosted** - Runs on your own hardware, no API costs
- ✅ **Privacy** - Doorbell conversations stay local
- ✅ **Fast** - No network latency to external APIs
- ✅ **Cost-effective** - One-time hardware investment vs. per-token pricing

## Hardware Requirements

### Minimum (Vicuna-7B):
- GPU: 16GB VRAM (RTX 4080, RTX 3090, etc.)
- RAM: 32GB system memory
- Storage: 15GB for model weights

### Recommended (Vicuna-13B):
- GPU: 24GB VRAM (RTX 4090, A5000, etc.)
- RAM: 64GB system memory
- Storage: 30GB for model weights

### Optimal (Vicuna-33B):
- GPU: 48GB+ VRAM (A100, multi-GPU setup)
- RAM: 128GB system memory
- Storage: 70GB for model weights

## Installation

### Option 1: FastChat (Recommended)

FastChat provides an OpenAI-compatible API server for Vicuna.

```bash
# Install FastChat
pip install "fschat[model_worker,webui]"

# Install additional dependencies
pip install aiohttp
```

### Option 2: vLLM (For Production)

vLLM offers better performance and throughput.

```bash
# Install vLLM
pip install vllm

# Install OpenAI compatibility layer
pip install openai
```

## Running Vicuna

### Method 1: FastChat (3-process setup)

**Terminal 1 - Controller:**
```bash
python -m fastchat.serve.controller
```

**Terminal 2 - Model Worker:**
```bash
# Vicuna-7B (lighter)
python -m fastchat.serve.model_worker \
    --model-path lmsys/vicuna-7b-v1.5 \
    --num-gpus 1

# OR Vicuna-13B (better quality)
python -m fastchat.serve.model_worker \
    --model-path lmsys/vicuna-13b-v1.5 \
    --num-gpus 1
```

**Terminal 3 - API Server:**
```bash
python -m fastchat.serve.openai_api_server \
    --host localhost \
    --port 8000
```

Test it works:
```bash
curl http://localhost:8000/v1/models
```

### Method 2: vLLM (Single process)

```bash
# Start vLLM server
python -m vllm.entrypoints.openai.api_server \
    --model lmsys/vicuna-13b-v1.5 \
    --host localhost \
    --port 8000 \
    --dtype float16
```

## echoBell Configuration

### Environment Variables

Create/edit `.env` in echoBell root:

```bash
# Vicuna Configuration
VICUNA_BASE_URL=http://localhost:8000
VICUNA_MODEL=vicuna-13b-v1.5

# Optional: Response tuning
VICUNA_TEMPERATURE=0.7
VICUNA_MAX_TOKENS=2048
```

### Code Configuration

```python
from packages.llm.conversation_handler import ConversationHandler

# Initialize with Vicuna
handler = ConversationHandler(
    conn=db_conn,
    asr_service=asr,
    tts_service=tts,
    llm_provider="vicuna",
    llm_config={
        "base_url": "http://localhost:8000",
        "model": "vicuna-13b-v1.5"
    }
)

# Use it
result = await handler.handle_doorbell_audio(
    audio_path="/path/to/doorbell.wav",
    context={"camera_id": 1, "visitor_info": {...}}
)
```

## Testing Vicuna

### Test 1: Simple Completion

```bash
curl http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "vicuna-13b-v1.5",
    "prompt": "Hello, who is at the door?",
    "max_tokens": 100
  }'
```

### Test 2: Chat Completion

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "vicuna-13b-v1.5",
    "messages": [
      {"role": "user", "content": "Someone rang my doorbell. What should I ask them?"}
    ]
  }'
```

### Test 3: echoBell Integration

```python
# Run the example
python examples/llm_conversation_example.py
```

## Performance Tuning

### GPU Optimization

```bash
# Enable tensor parallelism for multi-GPU
python -m fastchat.serve.model_worker \
    --model-path lmsys/vicuna-13b-v1.5 \
    --num-gpus 2 \
    --gpu-memory-utilization 0.9

# Use quantization for lower VRAM
python -m fastchat.serve.model_worker \
    --model-path lmsys/vicuna-13b-v1.5 \
    --load-8bit  # Requires bitsandbytes
```

### Response Speed

Adjust these for faster responses (may reduce quality):

```python
llm_config={
    "base_url": "http://localhost:8000",
    "model": "vicuna-13b-v1.5",
    "temperature": 0.5,      # Lower = more deterministic
    "max_tokens": 512,       # Shorter responses
    "top_p": 0.9            # Nucleus sampling
}
```

### Memory Management

```bash
# Limit CPU threads (if RAM constrained)
export OMP_NUM_THREADS=8

# Enable CPU offloading (slower but less VRAM)
python -m fastchat.serve.model_worker \
    --model-path lmsys/vicuna-13b-v1.5 \
    --cpu-offloading
```

## Prompt Engineering for Vicuna

Vicuna responds well to specific formats. For echoBell:

### Good Prompts:
```
USER: Someone rang the doorbell. They said: "I have a delivery for John."
Context: Unknown face, daytime, no scheduled deliveries.
What should I do?

ASSISTANT: I'll help you handle this delivery situation...
```

### Tool Calling Format:
```
To use a tool, respond with:
{"tool": "activate_asr", "parameters": {"question": "Who is the delivery from?"}}
```

Vicuna will learn to use this format after seeing examples.

## Troubleshooting

### Issue: "Connection refused"
- **Fix:** Ensure Vicuna server is running
- **Check:** `curl http://localhost:8000/v1/models`

### Issue: "CUDA out of memory"
- **Fix 1:** Use smaller model (vicuna-7b instead of 13b)
- **Fix 2:** Enable quantization (`--load-8bit`)
- **Fix 3:** Reduce `--gpu-memory-utilization` to 0.8

### Issue: "Slow responses (>30s)"
- **Fix 1:** Use vLLM instead of FastChat (3-5x faster)
- **Fix 2:** Reduce `max_tokens` in echoBell config
- **Fix 3:** Enable tensor parallelism on multi-GPU

### Issue: "Vicuna doesn't use tools correctly"
- **Fix:** Add few-shot examples to system prompt
- **Example:** Show 2-3 conversations where tools were used

### Issue: "Model downloaded but not loading"
- **Fix:** Check HuggingFace cache: `~/.cache/huggingface/`
- **Clear cache:** `rm -rf ~/.cache/huggingface/hub/models--lmsys--vicuna*`
- **Re-download:** Model worker will re-fetch

## Alternative Models

### Other Vicuna Versions:
- `lmsys/vicuna-7b-v1.5` - Lighter, faster
- `lmsys/vicuna-13b-v1.5-16k` - Longer context (16K tokens)
- `lmsys/vicuna-33b-v1.3` - Highest quality (requires 48GB+ VRAM)

### Other Open Models:
```python
# Mistral 7B (very fast, good quality)
llm_config={"model": "mistralai/Mistral-7B-Instruct-v0.2"}

# Llama 2 13B Chat
llm_config={"model": "meta-llama/Llama-2-13b-chat-hf"}

# Zephyr 7B (instruction-tuned)
llm_config={"model": "HuggingFaceH4/zephyr-7b-beta"}
```

## Production Deployment

### Systemd Service (Linux)

Create `/etc/systemd/system/vicuna.service`:

```ini
[Unit]
Description=Vicuna LLM Server for echoBell
After=network.target

[Service]
Type=simple
User=echobell
WorkingDirectory=/opt/echoBell
ExecStart=/usr/bin/python3 -m vllm.entrypoints.openai.api_server \
    --model lmsys/vicuna-13b-v1.5 \
    --host localhost \
    --port 8000 \
    --dtype float16
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable vicuna
sudo systemctl start vicuna
sudo systemctl status vicuna
```

### Docker (Cross-platform)

```dockerfile
FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y python3 python3-pip
RUN pip3 install vllm

EXPOSE 8000

CMD ["python3", "-m", "vllm.entrypoints.openai.api_server", \
     "--model", "lmsys/vicuna-13b-v1.5", \
     "--host", "0.0.0.0", \
     "--port", "8000"]
```

Run:
```bash
docker build -t vicuna-server .
docker run --gpus all -p 8000:8000 vicuna-server
```

## Monitoring

### Check Vicuna Health:
```bash
curl http://localhost:8000/v1/models
```

### Monitor GPU Usage:
```bash
nvidia-smi -l 1
```

### Monitor Conversation Logs:
```sql
-- Recent conversations
SELECT 
    session_id,
    camera_id,
    datetime(started_ts, 'unixepoch') as started,
    state,
    result_action
FROM llm_conversations
ORDER BY started_ts DESC
LIMIT 20;
```

## Cost Comparison

### Cloud APIs (per 1000 doorbell interactions):
- Claude Opus: ~$150/month
- GPT-4: ~$120/month
- GPT-3.5: ~$20/month

### Self-Hosted Vicuna:
- Hardware: $1500-3000 (one-time)
- Electricity: ~$15/month (24/7)
- **Break-even: 2-4 months**

## Next Steps

1. ✅ Install FastChat or vLLM
2. ✅ Download Vicuna model
3. ✅ Start Vicuna server
4. ✅ Test with curl
5. ✅ Configure echoBell
6. ✅ Run example: `python examples/llm_conversation_example.py`
7. ✅ Integrate with policy layer

## Support

- **FastChat Docs:** https://github.com/lm-sys/FastChat
- **vLLM Docs:** https://vllm.readthedocs.io/
- **Vicuna:** https://lmsys.org/blog/2023-03-30-vicuna/
- **echoBell LLM:** See `packages/llm/README.md`

---

**Last Updated:** February 1, 2026  
**Recommended:** Vicuna-13B with vLLM on RTX 4090
