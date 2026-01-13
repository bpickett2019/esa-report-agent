"""
MCP Server with SSE Transport for LangChain Agent Builder
Uses proper MCP SDK with Server-Sent Events transport
"""

import os
import uuid
import base64
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
import uvicorn

from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport

from pypdf import PdfReader, PdfWriter
import pdfplumber
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# ============================================================================
# Storage Setup
# ============================================================================

UPLOAD_DIR = Path(tempfile.gettempdir()) / "esa-mcp-uploads"
OUTPUT_DIR = Path(tempfile.gettempdir()) / "esa-mcp-outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

_jobs: dict[str, dict] = {}


def get_job(job_id: str) -> dict:
    if job_id not in _jobs:
        raise ValueError(f"Job {job_id} not found")
    return _jobs[job_id]


def save_job(job_id: str, data: dict) -> None:
    if job_id not in _jobs:
        _jobs[job_id] = {}
    _jobs[job_id].update(data)


# ============================================================================
# Initialize FastMCP
# ============================================================================

mcp = FastMCP("ESA Report Assembly Tools")

# ============================================================================
# MCP Tool Definitions
# ============================================================================

@mcp.tool()
def pdf_upload_intake(file_base64: str, filename: str) -> str:
    """
    Upload a PDF file and create a job for processing.

    Args:
        file_base64: Base64-encoded PDF file content
        filename: Original filename

    Returns:
        Job information with job_id, page count, and file metadata
    """
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


@mcp.tool()
def pdf_page_reader(job_id: str, page_numbers: list[int]) -> str:
    """
    Read and extract text from specific pages of a PDF to analyze document structure.

    Args:
        job_id: Job ID from pdf_upload_intake
        page_numbers: List of 1-indexed page numbers to read

    Returns:
        Extracted text from each requested page
    """
    try:
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

    except Exception as e:
        return f"Error reading pages: {str(e)}"


@mcp.tool()
def detect_report_structure(job_id: str, exec_summary_page: int, appendix_start_page: int, reasoning: str) -> str:
    """
    Register the detected structure boundaries for a report.

    Args:
        job_id: Job ID from pdf_upload_intake
        exec_summary_page: Page where Executive Summary begins (1-indexed)
        appendix_start_page: Page where Appendices begin (1-indexed)
        reasoning: Explanation of how boundaries were determined

    Returns:
        Confirmation of detected structure with page ranges
    """
    try:
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

    except Exception as e:
        return f"Error detecting structure: {str(e)}"


@mcp.tool()
def pdf_split(job_id: str) -> str:
    """
    Split the PDF into written_report.pdf and appendices.pdf based on detected structure.

    Args:
        job_id: Job ID with structure already detected

    Returns:
        Confirmation with file paths and page counts
    """
    try:
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

    except Exception as e:
        return f"Error splitting PDF: {str(e)}"


@mcp.tool()
def pdf_merge(job_id: str) -> str:
    """
    Merge split PDFs back together to create recompiled.pdf.

    Args:
        job_id: Job ID with split files already created

    Returns:
        Confirmation with recompiled file path and page count
    """
    try:
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

    except Exception as e:
        return f"Error merging PDFs: {str(e)}"


@mcp.tool()
def pdf_qc_analysis(job_id: str) -> str:
    """
    Run QC checks: verify page counts match, detect blank pages, generate QC summary.

    Args:
        job_id: Job ID with merge already completed

    Returns:
        QC report with pass/fail status
    """
    try:
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

    except Exception as e:
        return f"Error running QC: {str(e)}"


@mcp.tool()
def get_download_links(job_id: str) -> str:
    """
    Get download URLs for all generated files from a completed job.

    Args:
        job_id: Job ID to get files for

    Returns:
        List of all available output files with their paths
    """
    try:
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

    except Exception as e:
        return f"Error getting downloads: {str(e)}"


# ============================================================================
# FastAPI App with SSE Endpoint
# ============================================================================

app = FastAPI(
    title="ESA Report Assembly MCP Server (SSE)",
    description="PDF processing tools with MCP SSE transport for LangChain Agent Builder",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "service": "ESA Report Assembly MCP Server",
        "transport": "SSE",
        "mcp_endpoint": "/sse",
        "status": "ok"
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/sse")
async def sse_endpoint(request: Request):
    """
    MCP SSE endpoint for LangChain Agent Builder.
    This is the main endpoint that Agent Builder will connect to.
    """
    async def event_generator():
        transport = SseServerTransport("/messages")

        async with mcp.run_with_transport(transport) as connection:
            # Keep connection alive
            while True:
                await transport.send_event("ping", {})
                await connection.wait_for_close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ============================================================================
# Run Server
# ============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
