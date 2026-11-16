# 🤖 Local AI Assistant

A modular, offline-first, and privacy-focused personal AI assistant built with **Python (FastAPI)**, **Ollama**, and a self-contained **Alpine.js + TailwindCSS** web interface. 

Designed for extensibility and low resource overhead, it features dynamic task-based model routing, persistent SQLite chat history, real-time token streaming, and seamless fallback/integration with cloud providers like **OpenRouter**.

---

## ✨ Key Features

- **100% Offline-Capable UI:** All frontend dependencies (`TailwindCSS`, `Alpine.js`, `Marked.js`) are bundled locally—no external CDN calls required.
- **Pluggable Provider Architecture:** Easily switch between local inference (**Ollama**) and cloud APIs (**OpenRouter**, **GPT4All**) via a unified adapter interface.
- **Smart Task Routing (Orchestrator):** Automatically selects the optimal model (`general`, `coder`, `reasoning`) based on prompt intent, or allows manual model locking for low-RAM systems.
- **Low-Memory Optimization:** Configurable context window (`num_ctx`) and CPU thread limits to run smoothly on constrained hardware (4GB+ RAM).
- **Persistent Chat History:** Full conversation and message storage powered by SQLite.
- **Extensible Tooling Ready:** Built-in architectural hooks for RAG (Retrieval-Augmented Generation) and external connectors (e.g., GitHub).

---

## 🏗️ Project Structure

```text
local-ai-assistant/
├── config/
│   ├── settings.example.json   # Template configuration file
│   └── settings.json           # Active local settings (git-ignored)
├── core/
│   ├── providers/              # LLM provider adapters (Ollama, OpenRouter)
│   ├── config_manager.py       # Dynamic JSON configuration handler
│   ├── database.py             # SQLite persistence layer
│   └── orchestrator.py         # Model routing and prompt pipeline
├── data/                       # SQLite DB, documents, and vector stores
├── docs/                       # Architecture and versioning guides
├── static/                     # Self-contained frontend assets (HTML/JS)
├── tools/                      # External tool integrations
├── main.py                     # FastAPI application & SSE streaming endpoints
└── requirements.txt            # Python dependencies
```

---

## 🚀 Getting Started

### Prerequisites
- **Python 3.10+**
- **Ollama** installed and running locally (`http://127.0.0.1:11434`)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com
   cd local-ai-assistant
   ```

2. **Create and activate a virtual environment:**
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure settings:**
   Copy `config/settings.example.json` to `config/settings.json` and adjust your preferred models or API keys:
   ```powershell
   copy config\settings.example.json config\settings.json
   ```

5. **Run the application:**
   ```bash
   uvicorn main:app --reload --port 8000
   ```
   Open your browser and navigate to `http://127.0.0.1:8000`.

---

## 🛠️ Hardware Optimization (Low RAM Systems)

If running on systems with **4GB RAM**:
1. Pull lightweight models in Ollama:
   ```bash
   ollama pull qwen2.5-coder:0.5b
   ```
2. Set `"routing_mode": "coder"` in `config/settings.json` to prevent loading multiple large models simultaneously.
3. Alternatively, switch `active_provider` to `openrouter` in the UI Settings to offload inference to free cloud models.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
