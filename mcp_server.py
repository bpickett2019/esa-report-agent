"""
MCP Server for ESA Report Assembly Tools
Deploy this and connect Agent Builder via MCP
"""

import os
import json
import uuid
import tempfile
import base64
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from pypdf import PdfReader, PdfWriter
import pdfplumber
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# ============================================================================
# FastAPI App Setup
# ============================================================================

app = FastAPI(
    title="ESA Report Assembly MCP Server",
    description="PDF processing tools for Phase I ESA reports",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Storage (in-memory for demo, use Redis/S3 in production)
# ============================================================================

UPLOAD_DIR = Path(tempfile.gettempdir()) / "esa-mcp-uploads"
OUTPUT_DIR = Path(tempfile.gettempdir()) / "esa-mcp-outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

_jobs: dict[str, dict] = {}


def get_job(job_id: str) -> dict:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _jobs[job_id]


def save_job(job_id: str, data: dict) -> None:
    if job_id not in _jobs:
        _jobs[job_id] = {}
    _jobs[job_id].update(data)


# ============================================================================
# MCP Tool Definitions (for discovery)
# ============================================================================

MCP_TOOLS = [
    {
        "name": "pdf_upload_intake",
        "description": "Upload a PDF file and create a job for processing. Returns job_id, page count, and file metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_base64": {
                    "type": "string",
                    "description": "Base64-encoded PDF file content"
                },
                "filename": {
                    "type": "string",
                    "description": "Original filename"
                }
            },
            "required": ["file_base64", "filename"]
        }
    },
    {
        "name": "pdf_page_reader",
        "description": "Read and extract text from specific pages of a PDF to analyze document structure (TOC, Executive Summary, Appendix dividers).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID from pdf_upload_intake"},
                "page_numbers": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of 1-indexed page numbers to read"
                }
            },
            "required": ["job_id", "page_numbers"]
        }
    },
    {
        "name": "detect_report_structure",
        "description": "Register the detected structure boundaries. Call after analyzing pages to confirm Executive Summary and Appendix start pages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "exec_summary_page": {"type": "integer", "description": "Page where Executive Summary begins (1-indexed)"},
                "appendix_start_page": {"type": "integer", "description": "Page where Appendices begin (1-indexed)"},
                "reasoning": {"type": "string", "description": "Explanation of how boundaries were determined"}
            },
            "required": ["job_id", "exec_summary_page", "appendix_start_page", "reasoning"]
        }
    },
    {
        "name": "pdf_split",
        "description": "Split the PDF into written_report.pdf and appendices.pdf based on detected structure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "pdf_merge",
        "description": "Merge split PDFs back together to create recompiled.pdf and verify lossless splitting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "pdf_qc_analysis",
        "description": "Run QC checks: verify page counts match, detect blank pages, generate QC summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "get_download_links",
        "description": "Get download URLs for all generated files from a completed job.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"}
            },
            "required": ["job_id"]
        }
    }
]


# ============================================================================
# MCP Protocol Endpoints
# ============================================================================

@app.get("/")
async def root():
    return {"status": "ok", "service": "ESA Report Assembly MCP Server"}


@app.get("/mcp/tools")
async def list_tools():
    """MCP tool discovery endpoint"""
    return {"tools": MCP_TOOLS}


@app.post("/mcp/tools/{tool_name}")
async def call_tool(tool_name: str, params: dict = {}):
    """MCP tool execution endpoint"""
    
    tool_handlers = {
        "pdf_upload_intake": handle_pdf_upload,
        "pdf_page_reader": handle_page_reader,
        "detect_report_structure": handle_detect_structure,
        "pdf_split": handle_pdf_split,
        "pdf_merge": handle_pdf_merge,
        "pdf_qc_analysis": handle_qc_analysis,
        "get_download_links": handle_get_downloads,
    }
    
    if tool_name not in tool_handlers:
        raise HTTPException(status_code=404, detail=f"Tool {tool_name} not found")
    
    try:
        result = await tool_handlers[tool_name](params)
        return {"result": result}
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# Tool Handlers
# ============================================================================

async def handle_pdf_upload(params: dict) -> str:
    """Handle PDF upload via base64"""
    file_base64 = params.get("file_base64")
    filename = params.get("filename", "upload.pdf")
    
    if not file_base64:
        return "Error: file_base64 is required"
    
    try:
        # Decode base64
        file_bytes = base64.b64decode(file_base64)
        
        # Generate job ID
        job_id = str(uuid.uuid4())[:8]
        
        # Save file
        file_path = UPLOAD_DIR / f"{job_id}_{filename}"
        with open(file_path, "wb") as f:
            f.write(file_bytes)
        
        # Extract metadata
        reader = PdfReader(file_path)
        page_count = len(reader.pages)
        file_size_mb = len(file_bytes) / (1024 * 1024)
        
        # Store job
        save_job(job_id, {
            "file_path": str(file_path),
            "filename": filename,
            "page_count": page_count,
            "file_size_mb": round(file_size_mb, 2),
            "upload_time": datetime.now().isoformat()
        })
        
        return (
            f"PDF intake successful.\n"
            f"Job ID: {job_id}\n"
            f"File: {filename}\n"
            f"Pages: {page_count}\n"
            f"Size: {round(file_size_mb, 2)} MB\n"
            f"Status: Ready for structure detection"
        )
        
    except Exception as e:
        return f"Error processing PDF: {str(e)}"


async def handle_page_reader(params: dict) -> str:
    """Read specific pages from PDF"""
    job_id = params.get("job_id")
    page_numbers = params.get("page_numbers", [])
    
    if not job_id:
        return "Error: job_id is required"
    
    job = get_job(job_id)
    file_path = job["file_path"]
    
    results = []
    with pdfplumber.open(file_path) as pdf:
        total_pages = len(pdf.pages)
        
        for page_num in page_numbers:
            if page_num < 1 or page_num > total_pages:
                results.append(f"--- PAGE {page_num} ---\n[Invalid page number]")
                continue
            
            page = pdf.pages[page_num - 1]
            text = page.extract_text() or "[No text extracted]"
            
            if len(text) > 2000:
                text = text[:2000] + "\n[...truncated...]"
            
            results.append(f"--- PAGE {page_num} ---\n{text}")
    
    return "\n\n".join(results)


async def handle_detect_structure(params: dict) -> str:
    """Register detected structure"""
    job_id = params.get("job_id")
    exec_summary_page = params.get("exec_summary_page")
    appendix_start_page = params.get("appendix_start_page")
    reasoning = params.get("reasoning", "")
    
    if not all([job_id, exec_summary_page, appendix_start_page]):
        return "Error: job_id, exec_summary_page, and appendix_start_page are required"
    
    job = get_job(job_id)
    total_pages = job["page_count"]
    
    # Validate
    if exec_summary_page < 1:
        return "Error: exec_summary_page must be >= 1"
    if appendix_start_page <= exec_summary_page:
        return "Error: appendix_start_page must be after exec_summary_page"
    if appendix_start_page > total_pages:
        return f"Error: appendix_start_page exceeds total pages ({total_pages})"
    
    # Calculate ranges
    front_matter_range = (1, exec_summary_page - 1) if exec_summary_page > 1 else (0, 0)
    written_report_range = (exec_summary_page, appendix_start_page - 1)
    appendices_range = (appendix_start_page, total_pages)
    
    structure = {
        "front_matter_range": front_matter_range,
        "exec_summary_page": exec_summary_page,
        "written_report_range": written_report_range,
        "appendix_start_page": appendix_start_page,
        "appendices_range": appendices_range,
        "reasoning": reasoning
    }
    
    save_job(job_id, {"structure": structure})
    
    front_pages = front_matter_range[1] - front_matter_range[0] + 1 if front_matter_range[0] > 0 else 0
    written_pages = written_report_range[1] - written_report_range[0] + 1
    appendix_pages = appendices_range[1] - appendices_range[0] + 1
    
    return (
        f"Structure Detection Complete\n"
        f"{'=' * 40}\n"
        f"Job ID: {job_id}\n"
        f"Total Pages: {total_pages}\n\n"
        f"Detected Structure:\n"
        f"  • Front Matter: Pages {front_matter_range[0]}-{front_matter_range[1]} ({front_pages} pages)\n"
        f"  • Executive Summary: Page {exec_summary_page}\n"
        f"  • Written Report: Pages {written_report_range[0]}-{written_report_range[1]} ({written_pages} pages)\n"
        f"  • Appendices: Pages {appendices_range[0]}-{appendices_range[1]} ({appendix_pages} pages)\n\n"
        f"Status: Ready for splitting"
    )


async def handle_pdf_split(params: dict) -> str:
    """Split PDF into parts"""
    job_id = params.get("job_id")
    
    if not job_id:
        return "Error: job_id is required"
    
    job = get_job(job_id)
    
    if "structure" not in job:
        return "Error: Must run detect_report_structure first"
    
    structure = job["structure"]
    file_path = job["file_path"]
    
    reader = PdfReader(file_path)
    
    written_range = structure["written_report_range"]
    appendix_range = structure["appendices_range"]
    
    # Create output directory
    job_output_dir = OUTPUT_DIR / job_id
    job_output_dir.mkdir(exist_ok=True)
    
    # Split written report
    written_writer = PdfWriter()
    for page_num in range(written_range[0] - 1, written_range[1]):
        written_writer.add_page(reader.pages[page_num])
    
    written_path = job_output_dir / "written_report.pdf"
    with open(written_path, "wb") as f:
        written_writer.write(f)
    
    # Split appendices
    appendix_writer = PdfWriter()
    for page_num in range(appendix_range[0] - 1, appendix_range[1]):
        appendix_writer.add_page(reader.pages[page_num])
    
    appendix_path = job_output_dir / "appendices.pdf"
    with open(appendix_path, "wb") as f:
        appendix_writer.write(f)
    
    written_pages = written_range[1] - written_range[0] + 1
    appendix_pages = appendix_range[1] - appendix_range[0] + 1
    
    save_job(job_id, {
        "split": {
            "written_report_path": str(written_path),
            "written_report_pages": written_pages,
            "appendices_path": str(appendix_path),
            "appendices_pages": appendix_pages
        }
    })
    
    return (
        f"PDF Split Complete\n"
        f"{'=' * 40}\n"
        f"Job ID: {job_id}\n\n"
        f"Generated Files:\n"
        f"  ✓ written_report.pdf ({written_pages} pages)\n"
        f"  ✓ appendices.pdf ({appendix_pages} pages)\n\n"
        f"Status: Ready for recompilation"
    )


async def handle_pdf_merge(params: dict) -> str:
    """Merge PDFs back together"""
    job_id = params.get("job_id")
    
    if not job_id:
        return "Error: job_id is required"
    
    job = get_job(job_id)
    
    if "split" not in job:
        return "Error: Must run pdf_split first"
    
    split_data = job["split"]
    structure = job.get("structure", {})
    front_matter_range = structure.get("front_matter_range", (0, 0))
    
    writer = PdfWriter()
    total_pages = 0
    
    # Add front matter if exists
    if front_matter_range[0] > 0:
        original_reader = PdfReader(job["file_path"])
        for page_num in range(front_matter_range[0] - 1, front_matter_range[1]):
            writer.add_page(original_reader.pages[page_num])
            total_pages += 1
    
    # Add written report
    written_reader = PdfReader(split_data["written_report_path"])
    for page in written_reader.pages:
        writer.add_page(page)
        total_pages += 1
    
    # Add appendices
    appendix_reader = PdfReader(split_data["appendices_path"])
    for page in appendix_reader.pages:
        writer.add_page(page)
        total_pages += 1
    
    job_output_dir = OUTPUT_DIR / job_id
    recompiled_path = job_output_dir / "recompiled.pdf"
    
    with open(recompiled_path, "wb") as f:
        writer.write(f)
    
    save_job(job_id, {
        "merge": {
            "recompiled_path": str(recompiled_path),
            "recompiled_pages": total_pages
        }
    })
    
    return (
        f"PDF Merge Complete\n"
        f"{'=' * 40}\n"
        f"Job ID: {job_id}\n\n"
        f"Generated File:\n"
        f"  ✓ recompiled.pdf ({total_pages} pages)\n\n"
        f"Status: Ready for QC checks"
    )


async def handle_qc_analysis(params: dict) -> str:
    """Run QC checks"""
    job_id = params.get("job_id")
    
    if not job_id:
        return "Error: job_id is required"
    
    job = get_job(job_id)
    
    if "merge" not in job:
        return "Error: Must run pdf_merge first"
    
    original_pages = job["page_count"]
    recompiled_path = job["merge"]["recompiled_path"]
    
    recompiled_reader = PdfReader(recompiled_path)
    recompiled_pages = len(recompiled_reader.pages)
    
    page_count_match = original_pages == recompiled_pages
    
    # Detect blank pages
    blank_pages = []
    with pdfplumber.open(recompiled_path) as pdf:
        for i, page in enumerate(pdf.pages[:50]):
            text = page.extract_text()
            if not text or len(text.strip()) < 10:
                blank_pages.append(i + 1)
    
    qc_passed = page_count_match
    
    # Generate QC summary PDF
    job_output_dir = OUTPUT_DIR / job_id
    qc_summary_path = job_output_dir / "qc_summary.pdf"
    
    c = canvas.Canvas(str(qc_summary_path), pagesize=letter)
    width, height = letter
    
    y = height - 50
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "QC Summary Report")
    
    y -= 30
    c.setFont("Helvetica", 12)
    c.drawString(50, y, f"Job ID: {job_id}")
    y -= 20
    c.drawString(50, y, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    y -= 40
    c.setFont("Helvetica-Bold", 14)
    status_text = "QC PASSED" if qc_passed else "QC FAILED"
    c.drawString(50, y, status_text)
    
    y -= 30
    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Original page count: {original_pages}")
    y -= 18
    c.drawString(50, y, f"Recompiled page count: {recompiled_pages}")
    y -= 18
    c.drawString(50, y, f"Page count match: {'Yes' if page_count_match else 'NO'}")
    
    c.save()
    
    save_job(job_id, {
        "qc": {
            "original_pages": original_pages,
            "recompiled_pages": recompiled_pages,
            "page_count_match": page_count_match,
            "blank_pages": blank_pages[:20],
            "qc_passed": qc_passed,
            "qc_summary_path": str(qc_summary_path)
        }
    })
    
    status_emoji = "✓" if qc_passed else "✗"
    return (
        f"QC Analysis Complete\n"
        f"{'=' * 40}\n"
        f"Job ID: {job_id}\n\n"
        f"Status: {status_emoji} {'PASSED' if qc_passed else 'FAILED'}\n\n"
        f"Page Count Verification:\n"
        f"  • Original: {original_pages} pages\n"
        f"  • Recompiled: {recompiled_pages} pages\n"
        f"  • Match: {'✓ Yes' if page_count_match else '✗ No'}\n\n"
        f"Blank Pages Detected: {len(blank_pages)}"
    )


async def handle_get_downloads(params: dict) -> str:
    """Get download links"""
    job_id = params.get("job_id")
    
    if not job_id:
        return "Error: job_id is required"
    
    job = get_job(job_id)
    
    files = []
    base_url = f"/files/{job_id}"
    
    if "split" in job:
        files.append(("Written Report", f"{base_url}/written_report.pdf", job["split"]["written_report_pages"]))
        files.append(("Appendices", f"{base_url}/appendices.pdf", job["split"]["appendices_pages"]))
    
    if "merge" in job:
        files.append(("Recompiled", f"{base_url}/recompiled.pdf", job["merge"]["recompiled_pages"]))
    
    if "qc" in job:
        files.append(("QC Summary", f"{base_url}/qc_summary.pdf", 1))
    
    if not files:
        return f"No output files generated yet for job {job_id}"
    
    output = f"Download Links\n{'=' * 40}\nJob ID: {job_id}\n\nAvailable Files:\n"
    
    for name, url, pages in files:
        output += f"  📄 {name} ({pages} pages)\n     {url}\n\n"
    
    return output


# ============================================================================
# File Download Endpoints
# ============================================================================

@app.get("/files/{job_id}/{filename}")
async def download_file(job_id: str, filename: str):
    """Download generated files"""
    file_path = OUTPUT_DIR / job_id / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/pdf"
    )


# ============================================================================
# Direct Upload Endpoint (alternative to base64)
# ============================================================================

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Direct file upload endpoint"""
    job_id = str(uuid.uuid4())[:8]
    
    file_path = UPLOAD_DIR / f"{job_id}_{file.filename}"
    
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    reader = PdfReader(file_path)
    page_count = len(reader.pages)
    file_size_mb = len(content) / (1024 * 1024)
    
    save_job(job_id, {
        "file_path": str(file_path),
        "filename": file.filename,
        "page_count": page_count,
        "file_size_mb": round(file_size_mb, 2),
        "upload_time": datetime.now().isoformat()
    })
    
    return {
        "job_id": job_id,
        "filename": file.filename,
        "page_count": page_count,
        "file_size_mb": round(file_size_mb, 2),
        "status": "ready"
    }


# ============================================================================
# Health Check
# ============================================================================

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# ============================================================================
# Run Server
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
