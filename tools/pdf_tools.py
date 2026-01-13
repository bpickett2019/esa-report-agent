"""
PDF Processing Tools for Environmental Report Assembly Agent
Each tool is designed to be called by a LangChain agent.
"""

import os
import uuid
from typing import Optional
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader, PdfWriter
import pdfplumber
from pydantic import BaseModel, Field
from langchain_core.tools import tool


# Configuration
OUTPUT_DIR = Path(__file__).parent.parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


class PDFMetadata(BaseModel):
    """Metadata about an uploaded PDF"""
    job_id: str
    file_path: str
    file_name: str
    page_count: int
    file_size_mb: float
    upload_time: str


class StructureDetectionResult(BaseModel):
    """Result of structure detection"""
    job_id: str
    front_matter_range: tuple[int, int]  # (start, end) 1-indexed
    exec_summary_page: int
    written_report_range: tuple[int, int]
    appendix_start_page: int
    appendices_range: tuple[int, int]
    confidence: float
    reasoning: list[str]
    warnings: list[str]


class SplitResult(BaseModel):
    """Result of PDF splitting"""
    job_id: str
    written_report_path: str
    written_report_pages: int
    appendices_path: str
    appendices_pages: int


class MergeResult(BaseModel):
    """Result of PDF merging"""
    job_id: str
    recompiled_path: str
    recompiled_pages: int


class QCResult(BaseModel):
    """QC check results"""
    job_id: str
    original_pages: int
    recompiled_pages: int
    page_count_match: bool
    blank_pages_detected: list[int]
    potential_issues: list[str]
    qc_passed: bool
    qc_summary_path: str


# In-memory job storage (would be Redis/DB in production)
_jobs: dict[str, dict] = {}


def _get_job(job_id: str) -> dict:
    """Retrieve job data"""
    if job_id not in _jobs:
        raise ValueError(f"Job {job_id} not found")
    return _jobs[job_id]


def _save_job(job_id: str, data: dict) -> None:
    """Save job data"""
    if job_id not in _jobs:
        _jobs[job_id] = {}
    _jobs[job_id].update(data)


@tool
def pdf_upload_intake(file_path: str) -> str:
    """
    Accept a PDF file upload and extract basic metadata.
    Creates a job ID for tracking this processing session.
    
    Args:
        file_path: Path to the uploaded PDF file
        
    Returns:
        JSON string with job_id, page_count, file_size, and status
    """
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"
    
    try:
        job_id = str(uuid.uuid4())[:8]
        reader = PdfReader(file_path)
        page_count = len(reader.pages)
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        file_name = os.path.basename(file_path)
        
        metadata = PDFMetadata(
            job_id=job_id,
            file_path=file_path,
            file_name=file_name,
            page_count=page_count,
            file_size_mb=round(file_size_mb, 2),
            upload_time=datetime.now().isoformat()
        )
        
        # Store job data
        _save_job(job_id, {
            "metadata": metadata.model_dump(),
            "file_path": file_path,
            "page_count": page_count
        })
        
        return (
            f"PDF intake successful.\n"
            f"Job ID: {job_id}\n"
            f"File: {file_name}\n"
            f"Pages: {page_count}\n"
            f"Size: {metadata.file_size_mb} MB\n"
            f"Status: Ready for structure detection"
        )
        
    except Exception as e:
        return f"Error processing PDF: {str(e)}"


@tool
def pdf_page_reader(job_id: str, page_numbers: list[int]) -> str:
    """
    Read and extract text from specific pages of a PDF to analyze document structure.
    Use this to detect TOC, Executive Summary, Appendix dividers, etc.
    
    Args:
        job_id: The job ID from pdf_upload_intake
        page_numbers: List of 1-indexed page numbers to read (e.g., [1, 2, 3, 50, 51])
        
    Returns:
        Extracted text from each requested page with page numbers labeled
    """
    try:
        job = _get_job(job_id)
        file_path = job["file_path"]
        
        results = []
        with pdfplumber.open(file_path) as pdf:
            total_pages = len(pdf.pages)
            
            for page_num in page_numbers:
                if page_num < 1 or page_num > total_pages:
                    results.append(f"--- PAGE {page_num} ---\n[Invalid page number. Document has {total_pages} pages.]")
                    continue
                    
                page = pdf.pages[page_num - 1]  # Convert to 0-indexed
                text = page.extract_text() or "[No text extracted - may be image/scanned]"
                
                # Truncate very long pages for analysis
                if len(text) > 2000:
                    text = text[:2000] + "\n[...truncated for analysis...]"
                
                results.append(f"--- PAGE {page_num} ---\n{text}")
        
        return "\n\n".join(results)
        
    except Exception as e:
        return f"Error reading pages: {str(e)}"


@tool
def detect_report_structure(job_id: str, exec_summary_page: int, appendix_start_page: int, reasoning: str) -> str:
    """
    Register the detected structure boundaries for a report.
    Call this after analyzing pages with pdf_page_reader to confirm the structure.
    
    IMPORTANT: Before calling this, verify that:
    - exec_summary_page is the actual Executive Summary, not a TOC reference
    - appendix_start_page is the actual Appendix divider page, not a TOC reference
    
    Args:
        job_id: The job ID from pdf_upload_intake
        exec_summary_page: Page number where Executive Summary begins (1-indexed)
        appendix_start_page: Page number where Appendices section begins (1-indexed)
        reasoning: Explanation of how these boundaries were determined
        
    Returns:
        Confirmation of detected structure with page ranges
    """
    try:
        job = _get_job(job_id)
        total_pages = job["page_count"]
        
        # Validate boundaries
        warnings = []
        if exec_summary_page < 1:
            return "Error: exec_summary_page must be >= 1"
        if appendix_start_page <= exec_summary_page:
            return "Error: appendix_start_page must be after exec_summary_page"
        if appendix_start_page > total_pages:
            return f"Error: appendix_start_page ({appendix_start_page}) exceeds total pages ({total_pages})"
        
        # Calculate ranges
        front_matter_range = (1, exec_summary_page - 1) if exec_summary_page > 1 else (0, 0)
        written_report_range = (exec_summary_page, appendix_start_page - 1)
        appendices_range = (appendix_start_page, total_pages)
        
        # Basic confidence heuristic
        confidence = 0.85
        if appendix_start_page - exec_summary_page < 10:
            confidence -= 0.1
            warnings.append("Written report section seems short")
        if total_pages - appendix_start_page < 20:
            confidence -= 0.1
            warnings.append("Appendices section seems short for a typical ESA")
        
        result = StructureDetectionResult(
            job_id=job_id,
            front_matter_range=front_matter_range,
            exec_summary_page=exec_summary_page,
            written_report_range=written_report_range,
            appendix_start_page=appendix_start_page,
            appendices_range=appendices_range,
            confidence=round(confidence, 2),
            reasoning=reasoning.split(". "),
            warnings=warnings
        )
        
        # Store structure
        _save_job(job_id, {"structure": result.model_dump()})
        
        front_pages = front_matter_range[1] - front_matter_range[0] + 1 if front_matter_range[0] > 0 else 0
        written_pages = written_report_range[1] - written_report_range[0] + 1
        appendix_pages = appendices_range[1] - appendices_range[0] + 1
        
        output = (
            f"Structure Detection Complete\n"
            f"{'=' * 40}\n"
            f"Job ID: {job_id}\n"
            f"Total Pages: {total_pages}\n\n"
            f"Detected Structure:\n"
            f"  • Front Matter: Pages {front_matter_range[0]}-{front_matter_range[1]} ({front_pages} pages)\n"
            f"  • Executive Summary: Page {exec_summary_page}\n"
            f"  • Written Report: Pages {written_report_range[0]}-{written_report_range[1]} ({written_pages} pages)\n"
            f"  • Appendices: Pages {appendices_range[0]}-{appendices_range[1]} ({appendix_pages} pages)\n\n"
            f"Confidence: {confidence * 100:.0f}%\n"
        )
        
        if warnings:
            output += f"\nWarnings:\n" + "\n".join(f"  ⚠ {w}" for w in warnings)
        
        output += f"\n\nStatus: Ready for splitting"
        
        return output
        
    except Exception as e:
        return f"Error detecting structure: {str(e)}"


@tool
def pdf_split(job_id: str) -> str:
    """
    Split the PDF into separate files based on detected structure.
    Must call detect_report_structure first to establish boundaries.
    
    Generates:
    - written_report.pdf (Executive Summary through end of narrative)
    - appendices.pdf (Appendix divider through end of document)
    
    Args:
        job_id: The job ID with structure already detected
        
    Returns:
        Confirmation with file paths and page counts for each output
    """
    try:
        job = _get_job(job_id)
        
        if "structure" not in job:
            return "Error: Must run detect_report_structure first"
        
        structure = job["structure"]
        file_path = job["file_path"]
        
        reader = PdfReader(file_path)
        
        written_range = structure["written_report_range"]
        appendix_range = structure["appendices_range"]
        
        # Create output directory for this job
        job_output_dir = OUTPUT_DIR / job_id
        job_output_dir.mkdir(exist_ok=True)
        
        # Split written report
        written_writer = PdfWriter()
        for page_num in range(written_range[0] - 1, written_range[1]):  # Convert to 0-indexed
            written_writer.add_page(reader.pages[page_num])
        
        written_path = job_output_dir / "written_report.pdf"
        with open(written_path, "wb") as f:
            written_writer.write(f)
        
        # Split appendices
        appendix_writer = PdfWriter()
        for page_num in range(appendix_range[0] - 1, appendix_range[1]):  # Convert to 0-indexed
            appendix_writer.add_page(reader.pages[page_num])
        
        appendix_path = job_output_dir / "appendices.pdf"
        with open(appendix_path, "wb") as f:
            appendix_writer.write(f)
        
        written_pages = written_range[1] - written_range[0] + 1
        appendix_pages = appendix_range[1] - appendix_range[0] + 1
        
        result = SplitResult(
            job_id=job_id,
            written_report_path=str(written_path),
            written_report_pages=written_pages,
            appendices_path=str(appendix_path),
            appendices_pages=appendix_pages
        )
        
        _save_job(job_id, {"split": result.model_dump()})
        
        return (
            f"PDF Split Complete\n"
            f"{'=' * 40}\n"
            f"Job ID: {job_id}\n\n"
            f"Generated Files:\n"
            f"  ✓ written_report.pdf ({written_pages} pages)\n"
            f"    Path: {written_path}\n"
            f"  ✓ appendices.pdf ({appendix_pages} pages)\n"
            f"    Path: {appendix_path}\n\n"
            f"Status: Ready for recompilation"
        )
        
    except Exception as e:
        return f"Error splitting PDF: {str(e)}"


@tool
def pdf_merge(job_id: str) -> str:
    """
    Merge the split PDFs back together to verify lossless splitting.
    Creates recompiled.pdf from written_report.pdf + appendices.pdf.
    
    Args:
        job_id: The job ID with split files already created
        
    Returns:
        Confirmation with recompiled file path and page count
    """
    try:
        job = _get_job(job_id)
        
        if "split" not in job:
            return "Error: Must run pdf_split first"
        
        split_data = job["split"]
        
        written_path = split_data["written_report_path"]
        appendix_path = split_data["appendices_path"]
        
        # Check if we should include front matter
        structure = job.get("structure", {})
        front_matter_range = structure.get("front_matter_range", (0, 0))
        
        writer = PdfWriter()
        total_pages = 0
        
        # Add front matter if it exists
        if front_matter_range[0] > 0:
            original_reader = PdfReader(job["file_path"])
            for page_num in range(front_matter_range[0] - 1, front_matter_range[1]):
                writer.add_page(original_reader.pages[page_num])
                total_pages += 1
        
        # Add written report
        written_reader = PdfReader(written_path)
        for page in written_reader.pages:
            writer.add_page(page)
            total_pages += 1
        
        # Add appendices
        appendix_reader = PdfReader(appendix_path)
        for page in appendix_reader.pages:
            writer.add_page(page)
            total_pages += 1
        
        job_output_dir = OUTPUT_DIR / job_id
        recompiled_path = job_output_dir / "recompiled.pdf"
        
        with open(recompiled_path, "wb") as f:
            writer.write(f)
        
        result = MergeResult(
            job_id=job_id,
            recompiled_path=str(recompiled_path),
            recompiled_pages=total_pages
        )
        
        _save_job(job_id, {"merge": result.model_dump()})
        
        return (
            f"PDF Merge Complete\n"
            f"{'=' * 40}\n"
            f"Job ID: {job_id}\n\n"
            f"Generated File:\n"
            f"  ✓ recompiled.pdf ({total_pages} pages)\n"
            f"    Path: {recompiled_path}\n\n"
            f"Status: Ready for QC checks"
        )
        
    except Exception as e:
        return f"Error merging PDFs: {str(e)}"


@tool
def pdf_qc_analysis(job_id: str) -> str:
    """
    Perform quality control checks on the original and recompiled PDFs.
    Verifies page counts match and checks for common issues.
    
    Checks performed:
    - Page count comparison (original vs recompiled)
    - Blank page detection
    - Basic integrity verification
    
    Args:
        job_id: The job ID with merge already completed
        
    Returns:
        QC report with pass/fail status and any issues found
    """
    try:
        job = _get_job(job_id)
        
        if "merge" not in job:
            return "Error: Must run pdf_merge first"
        
        original_path = job["file_path"]
        recompiled_path = job["merge"]["recompiled_path"]
        original_pages = job["page_count"]
        
        # Read recompiled PDF
        recompiled_reader = PdfReader(recompiled_path)
        recompiled_pages = len(recompiled_reader.pages)
        
        page_count_match = original_pages == recompiled_pages
        
        # Detect blank pages in recompiled
        blank_pages = []
        with pdfplumber.open(recompiled_path) as pdf:
            for i, page in enumerate(pdf.pages[:50]):  # Check first 50 pages
                text = page.extract_text()
                if not text or len(text.strip()) < 10:
                    blank_pages.append(i + 1)
        
        # Compile issues
        issues = []
        if not page_count_match:
            issues.append(f"Page count mismatch: original={original_pages}, recompiled={recompiled_pages}")
        if blank_pages:
            issues.append(f"Potential blank pages detected: {blank_pages[:10]}")  # Show first 10
        
        qc_passed = page_count_match and len(issues) == 0
        
        # Generate QC summary PDF
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        
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
        status_text = "✓ QC PASSED" if qc_passed else "✗ QC FAILED"
        c.drawString(50, y, status_text)
        
        y -= 30
        c.setFont("Helvetica", 11)
        c.drawString(50, y, f"Original page count: {original_pages}")
        y -= 18
        c.drawString(50, y, f"Recompiled page count: {recompiled_pages}")
        y -= 18
        c.drawString(50, y, f"Page count match: {'Yes' if page_count_match else 'NO'}")
        y -= 18
        c.drawString(50, y, f"Blank pages detected: {len(blank_pages)}")
        
        if issues:
            y -= 30
            c.setFont("Helvetica-Bold", 12)
            c.drawString(50, y, "Issues Found:")
            c.setFont("Helvetica", 10)
            for issue in issues:
                y -= 15
                c.drawString(60, y, f"• {issue[:80]}")
        
        c.save()
        
        result = QCResult(
            job_id=job_id,
            original_pages=original_pages,
            recompiled_pages=recompiled_pages,
            page_count_match=page_count_match,
            blank_pages_detected=blank_pages[:20],  # Limit stored
            potential_issues=issues,
            qc_passed=qc_passed,
            qc_summary_path=str(qc_summary_path)
        )
        
        _save_job(job_id, {"qc": result.model_dump()})
        
        status_emoji = "✓" if qc_passed else "✗"
        output = (
            f"QC Analysis Complete\n"
            f"{'=' * 40}\n"
            f"Job ID: {job_id}\n\n"
            f"Status: {status_emoji} {'PASSED' if qc_passed else 'FAILED'}\n\n"
            f"Page Count Verification:\n"
            f"  • Original: {original_pages} pages\n"
            f"  • Recompiled: {recompiled_pages} pages\n"
            f"  • Match: {'✓ Yes' if page_count_match else '✗ No'}\n\n"
            f"Blank Page Detection:\n"
            f"  • Found: {len(blank_pages)} potential blank pages\n"
        )
        
        if blank_pages:
            output += f"  • Pages: {blank_pages[:10]}{'...' if len(blank_pages) > 10 else ''}\n"
        
        if issues:
            output += f"\nIssues:\n" + "\n".join(f"  ⚠ {i}" for i in issues)
        
        output += f"\n\nQC Summary PDF: {qc_summary_path}"
        
        return output
        
    except Exception as e:
        return f"Error running QC: {str(e)}"


@tool
def get_download_links(job_id: str) -> str:
    """
    Get download links for all generated files from a completed job.
    
    Args:
        job_id: The job ID to get files for
        
    Returns:
        List of all available output files with their paths
    """
    try:
        job = _get_job(job_id)
        
        job_output_dir = OUTPUT_DIR / job_id
        
        files = []
        
        if "split" in job:
            files.append(("Written Report", job["split"]["written_report_path"], job["split"]["written_report_pages"]))
            files.append(("Appendices", job["split"]["appendices_path"], job["split"]["appendices_pages"]))
        
        if "merge" in job:
            files.append(("Recompiled", job["merge"]["recompiled_path"], job["merge"]["recompiled_pages"]))
        
        if "qc" in job:
            files.append(("QC Summary", job["qc"]["qc_summary_path"], 1))
        
        if not files:
            return f"No output files generated yet for job {job_id}"
        
        output = (
            f"Download Links\n"
            f"{'=' * 40}\n"
            f"Job ID: {job_id}\n\n"
            f"Available Files:\n"
        )
        
        for name, path, pages in files:
            output += f"  📄 {name} ({pages} pages)\n"
            output += f"     {path}\n\n"
        
        return output
        
    except Exception as e:
        return f"Error getting downloads: {str(e)}"


# Export all tools
PDF_TOOLS = [
    pdf_upload_intake,
    pdf_page_reader,
    detect_report_structure,
    pdf_split,
    pdf_merge,
    pdf_qc_analysis,
    get_download_links,
]
