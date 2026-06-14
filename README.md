PadelAnalysis
=================

Minimal starter workspace to connect to an MCP remote server and build tools.

Quickstart

1. Set your RapidAPI key in an environment variable:

```bash
set RAPIDAPI_KEY=your_key_here   # Windows (cmd)
# or
export RAPIDAPI_KEY=your_key_here # macOS / Linux
```

2. (Optional) Run the MCP remote proxy locally using `npx mcp-remote`:

```bash
npx mcp-remote https://mcp.rapidapi.com --header "x-api-host: padelfirst.p.rapidapi.com" --header "x-api-key: $RAPIDAPI_KEY"
```

3. Install dependencies and run the FastAPI app:

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

4. Open http://localhost:8000 in your browser.

Notes
- This project provides a small `MCPClient` helper (see `padel_analysis/mcp_client.py`) to build and launch the recommended `npx mcp-remote` command from Python.
- Secrets should be provided via environment variables (recommended) or a local `.env` file.
