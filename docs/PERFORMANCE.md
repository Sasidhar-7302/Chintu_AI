# Performance Optimization Guide for Chintu AI Assistant

This guide provides optimizations specifically for running Chintu on **Dell Inspiron 5000 Series** with:
- **CPU**: Intel i5 8th Gen (Quad-core with hyperthreading = 8 threads)
- **RAM**: 24GB
- **Graphics**: Integrated Intel UHD Graphics 620 (2GB)
- **Storage**: 512GB SSD

## Overview of Optimizations Applied

### 1. **Local LLM Optimization** ✅

**Changed Model**: `qwen2.5:1.5b` → `tinyllama` (~600MB)

**Why**: 
- tinyllama is 3-4x faster on CPU-only inference
- Uses ~1GB RAM vs ~3GB for qwen2.5:1.5b
- Still produces decent quality responses for most tasks

**Alternative Models** (if you want better quality):
- `phi-2` (~1.3B, better quality, still fast on CPU)
- `qwen2:0.5b` (~350MB, very fast, decent quality)

**Settings Applied**:
- `llm_max_tokens`: 1024 (reduced from 2048)
- `llm_num_threads`: 4 (optimized for your CPU)
- `llm_num_ctx`: 2048 (context window)
- `llm_num_gpu`: 0 (CPU-only mode)

### 2. **Speech-to-Text (Whisper) Optimization** ✅

**Changed Model**: `base.en` → `tiny.en`

**Why**:
- tiny.en is ~3x faster on CPU
- Uses ~50MB RAM vs ~150MB for base.en
- Accuracy difference is minimal for clear speech

**Settings Applied**:
- `stt_compute_type`: `int8` (fastest CPU mode)
- `stt_cpu_threads`: 4 (uses your CPU threads efficiently)
- `stt_beam_size`: 1 (faster decoding)
- `stt_num_workers`: 1 (reduces memory overhead)

### 3. **Hardware Auto-Detection** ✅

The system now automatically detects your hardware and optimizes settings. This is handled by `chintu/core/hardware_optimizer.py`.

**Your Profile**: `mid_range` (16-32GB RAM, CPU-only)

### 4. **Memory (ChromaDB) Optimization** ✅

**Settings Applied**:
- `memory_top_k`: 3 (reduced from 4) - fewer memory retrievals = faster
- Uses optimized batch sizes for embeddings

### 5. **Resource Management** ✅

- Automatic model selection based on available RAM/CPU
- CPU thread limits to prevent overload
- Reduced context windows for memory efficiency

## Expected Performance Improvements

| Component | Before | After | Improvement |
|-----------|--------|-------|-------------|
| Local LLM Response | ~5-10s | ~2-4s | **2-3x faster** |
| STT Transcription | ~3-5s | ~1-2s | **2-3x faster** |
| Memory Usage (LLM) | ~3GB | ~1GB | **67% reduction** |
| Memory Usage (STT) | ~150MB | ~50MB | **67% reduction** |
| Overall RAM Usage | ~8-10GB | ~4-6GB | **40-50% reduction** |

## Running Chintu Optimized

### 1. Install Updated Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Ollama Models

Make sure you have the optimized model installed:

```bash
# Install tinyllama (recommended for your hardware)
ollama pull tinyllama

# OR if you want better quality (slower):
ollama pull phi-2
```

### 3. Configure .env File

Create a `.env` file in the project root:

```env
# Groq API (free tier) - fast cloud LLM for complex tasks
GROQ_API_KEY=your-groq-api-key-here

# Gemini API (free tier) - for research/complex tasks
GOOGLE_AI_KEY=your-gemini-api-key-here

# Disable auto-optimization if you want to manually configure
# CHINTU_AUTO_OPTIMIZE=false
```

### 4. Run Chintu

```bash
python main.py
```

The system will automatically:
1. Detect your hardware
2. Apply optimizations
3. Log the optimizations applied

## Manual Configuration Overrides

If you want to override auto-optimization, set these in `.env` or `config.py`:

```env
# Use a larger model (slower but better quality)
CHINTU_OLLAMA_MODEL=phi-2

# Use better STT model (slower but more accurate)
CHINTU_WHISPER_MODEL=base.en

# Adjust CPU threads (match your CPU)
CHINTU_LLM_NUM_THREADS=4
CHINTU_STT_CPU_THREADS=4
```

## Troubleshooting Performance Issues

### If Chintu is Still Slow:

1. **Check Ollama is Running**:
   ```bash
   ollama serve
   ```

2. **Verify Model is Installed**:
   ```bash
   ollama list
   ```

3. **Monitor Resource Usage**:
   - Open Task Manager (Windows)
   - Check CPU and RAM usage
   - Should see ~20-30% CPU, ~4-6GB RAM when idle

4. **Disable Heavy Features**:
   - Set `gesture_enabled: false` in config (already default)
   - Disable hand tracking if not needed
   - Reduce `memory_top_k` to 2 if still slow

### If You Get Out of Memory Errors:

1. **Use Even Smaller Model**:
   ```env
   CHINTU_OLLAMA_MODEL=qwen2:0.5b
   ```

2. **Disable Memory**:
   ```env
   CHINTU_MEMORY_ENABLED=false
   ```

3. **Reduce Context Window**:
   ```env
   CHINTU_LLM_NUM_CTX=1024
   ```

## Upgrade Path (3-4 Months)

When you upgrade your hardware, you can:

1. **Enable GPU Acceleration** (if you get a dedicated GPU):
   - Install CUDA and PyTorch with GPU support
   - Set `whisper_device: cuda` in config
   - Ollama will auto-detect GPU

2. **Use Larger Models**:
   - Switch to `phi-2` or `qwen2.5:1.5b` for better quality
   - Use `base.en` or `small.en` for STT

3. **Increase Context Windows**:
   - Set `llm_max_tokens: 2048` or higher
   - Increase `llm_num_ctx` for longer conversations

## Performance Monitoring

The system logs performance metrics. Check logs for:
- Model selection decisions
- Response times
- Resource usage

Example log output:
```
INFO: Hardware detected: 8 CPU threads, 24.0GB RAM, GPU: False, Profile: mid_range
INFO: Optimized ollama_model = tinyllama for mid_range hardware
INFO: Optimized whisper_model = tiny.en for mid_range hardware
```

## Summary

Your current setup is now optimized for:
- ✅ **Fast local LLM inference** (~2-4s responses)
- ✅ **Fast speech transcription** (~1-2s)
- ✅ **Efficient memory usage** (~4-6GB RAM)
- ✅ **Smart cloud fallback** (Groq/Gemini for complex tasks)

The system will **automatically use Groq/Gemini** for complex tasks when available, and fall back to the local LLM for simple queries or when offline. This gives you the best of both worlds: **fast local responses** for common tasks and **powerful cloud AI** for complex ones.

## Questions?

If you experience issues, check:
1. All dependencies are installed
2. Ollama is running with the correct model
3. `.env` file has API keys (for cloud fallback)
4. Hardware auto-detection is working (check logs)

For more help, see `DOCUMENTATION.md` or check the logs for specific errors.

