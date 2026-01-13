"""
Demo script that creates a sample Phase I ESA report and processes it.
Run this to see the full workflow in action.
"""

import os
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))


def create_sample_esa_report(output_path: str = "sample_esa_report.pdf") -> str:
    """
    Create a sample Phase I ESA report PDF for testing.
    This simulates the structure of a real report.
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
    from reportlab.lib.units import inch
    
    doc = SimpleDocTemplate(output_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    # Page 1: Cover
    story.append(Paragraph("PHASE I ENVIRONMENTAL SITE ASSESSMENT", styles['Title']))
    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph("123 Industrial Boulevard", styles['Heading2']))
    story.append(Paragraph("Springfield, State 12345", styles['Heading2']))
    story.append(Spacer(1, inch))
    story.append(Paragraph("Prepared For:", styles['Normal']))
    story.append(Paragraph("ABC Development Corporation", styles['Normal']))
    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph("Prepared By:", styles['Normal']))
    story.append(Paragraph("Environmental Consulting Services, Inc.", styles['Normal']))
    story.append(Paragraph("January 2025", styles['Normal']))
    story.append(PageBreak())
    
    # Page 2-3: Table of Contents
    story.append(Paragraph("TABLE OF CONTENTS", styles['Heading1']))
    story.append(Spacer(1, 0.25*inch))
    toc_items = [
        ("1.0 EXECUTIVE SUMMARY", "4"),
        ("2.0 INTRODUCTION", "6"),
        ("3.0 SITE DESCRIPTION", "8"),
        ("4.0 USER PROVIDED INFORMATION", "12"),
        ("5.0 RECORDS REVIEW", "15"),
        ("6.0 SITE RECONNAISSANCE", "22"),
        ("7.0 INTERVIEWS", "28"),
        ("8.0 FINDINGS AND CONCLUSIONS", "32"),
        ("9.0 QUALIFICATIONS", "35"),
        ("APPENDIX A - SITE MAPS", "38"),
        ("APPENDIX B - SITE PHOTOGRAPHS", "45"),
        ("APPENDIX C - REGULATORY RECORDS", "52"),
        ("APPENDIX D - HISTORICAL SOURCES", "68"),
    ]
    for item, page in toc_items:
        story.append(Paragraph(f"{item} {'.'*20} {page}", styles['Normal']))
        story.append(Spacer(1, 0.1*inch))
    story.append(PageBreak())
    
    # Page 3: More TOC / Certifications
    story.append(Paragraph("PROFESSIONAL CERTIFICATIONS", styles['Heading1']))
    story.append(Spacer(1, 0.25*inch))
    story.append(Paragraph("This Phase I Environmental Site Assessment has been prepared in accordance with ASTM E1527-21.", styles['Normal']))
    story.append(PageBreak())
    
    # Page 4-5: Executive Summary
    story.append(Paragraph("1.0 EXECUTIVE SUMMARY", styles['Heading1']))
    story.append(Spacer(1, 0.25*inch))
    exec_summary_text = """
    Environmental Consulting Services, Inc. (ECS) has completed this Phase I Environmental 
    Site Assessment (ESA) of the property located at 123 Industrial Boulevard, Springfield. 
    This assessment was conducted in accordance with ASTM Standard E1527-21.
    
    The subject property consists of approximately 5.2 acres of land improved with a 
    45,000 square foot industrial building currently used for light manufacturing operations.
    
    Based on our investigation, ECS has identified the following Recognized Environmental 
    Conditions (RECs) in connection with the subject property:
    
    • Historical use of chlorinated solvents in degreasing operations
    • Presence of an underground storage tank (UST) of unknown status
    
    ECS recommends additional investigation to evaluate these RECs.
    """
    for para in exec_summary_text.strip().split('\n\n'):
        story.append(Paragraph(para.strip(), styles['Normal']))
        story.append(Spacer(1, 0.15*inch))
    story.append(PageBreak())
    
    # Pages 6-37: Written Report Body (simplified)
    sections = [
        ("2.0 INTRODUCTION", 3),
        ("3.0 SITE DESCRIPTION", 4),
        ("4.0 USER PROVIDED INFORMATION", 3),
        ("5.0 RECORDS REVIEW", 7),
        ("6.0 SITE RECONNAISSANCE", 6),
        ("7.0 INTERVIEWS", 4),
        ("8.0 FINDINGS AND CONCLUSIONS", 4),
        ("9.0 QUALIFICATIONS", 3),
    ]
    
    lorem = """
    This section provides detailed information regarding the assessment activities 
    and findings. The information contained herein was gathered through document review, 
    site reconnaissance, interviews with knowledgeable parties, and review of regulatory 
    records. All activities were conducted in accordance with ASTM E1527-21 requirements.
    
    The environmental professional has exercised appropriate professional judgment in 
    conducting this assessment. The conclusions presented are based on the information 
    available at the time of the assessment.
    """
    
    for section_title, num_pages in sections:
        story.append(Paragraph(section_title, styles['Heading1']))
        story.append(Spacer(1, 0.25*inch))
        for _ in range(num_pages):
            for para in lorem.strip().split('\n\n'):
                story.append(Paragraph(para.strip(), styles['Normal']))
                story.append(Spacer(1, 0.15*inch))
        story.append(PageBreak())
    
    # Page 38: APPENDIX A DIVIDER (this is what we need to detect!)
    story.append(Spacer(1, 3*inch))
    story.append(Paragraph("APPENDIX A", styles['Title']))
    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph("SITE MAPS", styles['Heading1']))
    story.append(PageBreak())
    
    # Pages 39-44: Appendix A content (site maps placeholder)
    for i in range(6):
        story.append(Paragraph(f"FIGURE A-{i+1}", styles['Heading2']))
        story.append(Paragraph(f"Site Map - View {i+1}", styles['Normal']))
        story.append(Spacer(1, 0.5*inch))
        story.append(Paragraph("[Site map graphic would be inserted here]", styles['Italic']))
        story.append(PageBreak())
    
    # Page 45: APPENDIX B DIVIDER
    story.append(Spacer(1, 3*inch))
    story.append(Paragraph("APPENDIX B", styles['Title']))
    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph("SITE PHOTOGRAPHS", styles['Heading1']))
    story.append(PageBreak())
    
    # Pages 46-51: Appendix B content
    for i in range(6):
        story.append(Paragraph(f"PHOTO LOG - PAGE {i+1}", styles['Heading2']))
        story.append(Paragraph(f"Photographs taken during site reconnaissance", styles['Normal']))
        story.append(Spacer(1, 0.25*inch))
        for j in range(4):
            story.append(Paragraph(f"Photo {i*4+j+1}: [Description of site feature]", styles['Normal']))
            story.append(Spacer(1, 0.1*inch))
        story.append(PageBreak())
    
    # Page 52: APPENDIX C DIVIDER
    story.append(Spacer(1, 3*inch))
    story.append(Paragraph("APPENDIX C", styles['Title']))
    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph("REGULATORY RECORDS", styles['Heading1']))
    story.append(PageBreak())
    
    # Pages 53-67: Appendix C content
    for i in range(15):
        story.append(Paragraph(f"REGULATORY RECORD {i+1}", styles['Heading2']))
        story.append(Paragraph("Database search results and regulatory correspondence.", styles['Normal']))
        story.append(Spacer(1, 0.25*inch))
        story.append(Paragraph(lorem.strip(), styles['Normal']))
        story.append(PageBreak())
    
    # Page 68: APPENDIX D DIVIDER
    story.append(Spacer(1, 3*inch))
    story.append(Paragraph("APPENDIX D", styles['Title']))
    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph("HISTORICAL SOURCES", styles['Heading1']))
    story.append(PageBreak())
    
    # Pages 69-75: Appendix D content
    for i in range(7):
        story.append(Paragraph(f"HISTORICAL SOURCE {i+1}", styles['Heading2']))
        story.append(Paragraph("Historical aerial photographs and fire insurance maps.", styles['Normal']))
        story.append(Spacer(1, 0.25*inch))
        story.append(Paragraph(lorem.strip(), styles['Normal']))
        if i < 6:
            story.append(PageBreak())
    
    # Build the PDF
    doc.build(story)
    
    print(f"✓ Created sample ESA report: {output_path}")
    
    # Verify page count
    from pypdf import PdfReader
    reader = PdfReader(output_path)
    print(f"✓ Total pages: {len(reader.pages)}")
    
    return output_path


def run_demo():
    """Run the full demo"""
    print("\n" + "="*60)
    print("ESA Report Assembly Agent - Demo")
    print("="*60 + "\n")
    
    # Check dependencies
    try:
        from pypdf import PdfReader
        from reportlab.lib.pagesizes import letter
        import pdfplumber
        print("✓ All PDF dependencies available")
    except ImportError as e:
        print(f"✗ Missing dependency: {e}")
        print("\nInstall with: pip install pypdf pdfplumber reportlab")
        return
    
    # Check for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\n⚠ ANTHROPIC_API_KEY not set")
        print("\nTo run the full demo, set your API key:")
        print("  export ANTHROPIC_API_KEY=your-key-here")
        print("\nGenerating sample PDF anyway for inspection...\n")
        create_sample_esa_report("sample_esa_report.pdf")
        return
    
    print("✓ Anthropic API key found")
    
    # Check LangSmith
    if os.environ.get("LANGCHAIN_API_KEY"):
        print("✓ LangSmith tracing enabled")
    else:
        print("○ LangSmith tracing disabled (optional)")
    
    print("\n" + "-"*60 + "\n")
    
    # Create sample report
    sample_path = create_sample_esa_report("sample_esa_report.pdf")
    
    print("\n" + "-"*60)
    print("Running Agent...")
    print("-"*60 + "\n")
    
    # Run the agent
    from agent import create_agent, process_report
    
    agent = create_agent()
    result = process_report(agent, sample_path)
    
    print("\n" + "="*60)
    print("Demo Complete")
    print("="*60)
    print("\nCheck the ./outputs directory for generated files")
    print("If LangSmith is configured, view traces at https://smith.langchain.com")


if __name__ == "__main__":
    run_demo()
