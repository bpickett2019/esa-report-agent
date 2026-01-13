# ESA Report Assembly Agent

LangChain-powered agent for deconstructing, QC checking, and reassembling Phase I Environmental Site Assessment (ESA) reports.

## Two Ways to Run

### Option 1: Standalone Agent (Local)
Run the agent directly with your Anthropic API key.

### Option 2: MCP Server + LangChain Agent Builder
Deploy the MCP server and connect it to Agent Builder for a visual workflow.

---

## Quick Start (Standalone)

```bash
# Install dependencies
pip install -r requirements.txt

# Set API key
export ANTHROPIC_API_KEY=your-key

# Run demo
python demo.py
```

---

## Deploy MCP Server (For Agent Builder)

### Option A: Railway (Recommended)

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app)
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your repo
5. Railway auto-detects the Procfile and deploys
6. Copy your URL: `https://your-app.up.railway.app`

### Option B: Fly.io

```bash
# Install flyctl
brew install flyctl

# Login
fly auth login

# Launch (from project directory)
fly launch

# Deploy
fly deploy
```

### Option C: Local (For Testing)

```bash
# Run server
python mcp_server.py

# Server runs at http://localhost:8000
```

---

## Connect to LangChain Agent Builder

Once deployed, connect to Agent Builder:

1. Open your agent in Agent Builder
2. Click **TOOLBOX → MCP**
3. Enter your server URL: `https://your-app.up.railway.app`
4. Agent Builder will discover all 7 tools automatically

### MCP Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /mcp/tools` | Tool discovery (Agent Builder calls this) |
| `POST /mcp/tools/{name}` | Execute a tool |
| `GET /files/{job_id}/{file}` | Download generated files |
| `POST /upload` | Direct file upload (alternative) |

---

## Tools Available

| Tool | Description |
|------|-------------|
| `pdf_upload_intake` | Accept PDF (base64), create job ID |
| `pdf_page_reader` | Read specific pages for structure analysis |
| `detect_report_structure` | Register boundaries (exec summary, appendix) |
| `pdf_split` | Split into written_report.pdf + appendices.pdf |
| `pdf_merge` | Recompile for verification |
| `pdf_qc_analysis` | Run QC, generate summary PDF |
| `get_download_links` | List output files with download URLs |

---

## Project Structure

```
esa-report-agent/
├── mcp_server.py     # FastAPI MCP server (deploy this)
├── agent.py          # Standalone LangChain agent
├── demo.py           # Demo with sample PDF
├── tools/
│   └── pdf_tools.py  # PDF processing tools
├── Procfile          # For Railway/Heroku
├── railway.json      # Railway config
└── requirements.txt
```

---

## Test MCP Server Locally

```bash
# Start server
python mcp_server.py

# In another terminal, test tool discovery
curl http://localhost:8000/mcp/tools

# Test health
curl http://localhost:8000/health
```

---

## Workflow Example

```
User uploads PDF via Agent Builder

Agent calls: pdf_upload_intake
→ Returns: job_id, page count

Agent calls: pdf_page_reader (pages 1-5, 40-50)
→ Returns: extracted text for structure analysis

Agent calls: detect_report_structure
→ Registers: exec_summary=4, appendix_start=47

Agent calls: pdf_split
→ Creates: written_report.pdf, appendices.pdf

Agent calls: pdf_merge
→ Creates: recompiled.pdf

Agent calls: pdf_qc_analysis
→ Returns: QC passed, page counts match

Agent calls: get_download_links
→ Returns: download URLs for all files
```

---

## LangSmith Tracing

For the standalone agent, set these environment variables:

```bash
export LANGCHAIN_API_KEY=your-langsmith-key
export LANGCHAIN_PROJECT=esa-report-agent
export LANGCHAIN_TRACING_V2=true
```

View traces at: https://smith.langchain.com
