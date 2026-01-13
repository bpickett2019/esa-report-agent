"""
Environmental Report Assembly Agent
Built with LangChain + LangSmith tracing
"""

import os
from typing import Optional
from dotenv import load_dotenv

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.prebuilt import create_react_agent
from langsmith import traceable

from tools.pdf_tools import PDF_TOOLS

# Load environment variables
load_dotenv()


# System prompt for the agent
SYSTEM_PROMPT = """You are an Environmental Report Assembly Assistant that helps environmental consulting firms deconstruct, QC, and reassemble Phase I ESA (Environmental Site Assessment) reports.

## YOUR WORKFLOW

You have access to the following tools to process environmental reports:

1. **pdf_upload_intake** - Start here. Accept a PDF and create a job ID.
2. **pdf_page_reader** - Read specific pages to analyze document structure.
3. **detect_report_structure** - Register the detected boundaries (exec summary, appendix start).
4. **pdf_split** - Split into written_report.pdf and appendices.pdf.
5. **pdf_merge** - Recompile to verify lossless splitting.
6. **pdf_qc_analysis** - Run QC checks and generate summary.
7. **get_download_links** - Provide final download links.

## CRITICAL RULES FOR STRUCTURE DETECTION

When analyzing a report to find the Executive Summary and Appendix boundaries:

1. **ALWAYS read multiple pages** - Start with pages 1-5 to find TOC and front matter, then sample pages around suspected boundaries.

2. **REJECT FALSE POSITIVES** - The Table of Contents will list "Appendix A" with a page number. This is NOT the appendix start. The actual appendix divider is:
   - A standalone page with just "APPENDIX A" or "APPENDICES"
   - Often followed by site maps, photos, or technical data
   - Usually in the latter half of the document

3. **VERIFY BEFORE CONFIRMING** - Before calling detect_report_structure, read the suspected appendix start page AND the page before it to confirm it's the actual divider.

4. **EXPLAIN YOUR REASONING** - When calling detect_report_structure, provide clear reasoning for why you chose those page numbers.

## TYPICAL PHASE I ESA STRUCTURE

- Cover Page (page 1)
- Table of Contents (pages 2-4)
- Executive Summary (page 5-10)
- Written Report / Narrative (varies, typically 30-60 pages)
- Appendix A: Site Maps
- Appendix B: Site Photographs
- Appendix C: Regulatory Records
- Additional Appendices...

## BEHAVIOR

- Be concise and professional
- Report progress at each step
- If structure detection is uncertain (confidence < 70%), ask the user to confirm
- Always show page counts so the user can verify
- Complete the full workflow unless the user asks to stop

When you receive a PDF path, immediately begin processing without asking for confirmation."""


def create_agent(model_name: str = "claude-sonnet-4-20250514"):
    """
    Create the ESA Report Assembly agent with all PDF tools.
    
    Args:
        model_name: Anthropic model to use
        
    Returns:
        Configured LangGraph agent
    """
    # Initialize the LLM
    llm = ChatAnthropic(
        model=model_name,
        temperature=0,
        max_tokens=4096,
    )
    
    # Create the agent with tools
    agent = create_react_agent(
        llm,
        PDF_TOOLS,
        state_modifier=SYSTEM_PROMPT,
    )
    
    return agent


@traceable(name="process_report")
def process_report(agent, pdf_path: str, verbose: bool = True) -> dict:
    """
    Process a PDF report through the full workflow.
    
    Args:
        agent: The configured agent
        pdf_path: Path to the PDF file
        verbose: Whether to print progress
        
    Returns:
        Final state with all results
    """
    initial_message = f"Process this environmental report: {pdf_path}"
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"Starting Report Processing")
        print(f"{'='*60}")
        print(f"Input: {pdf_path}\n")
    
    # Run the agent
    result = agent.invoke({
        "messages": [HumanMessage(content=initial_message)]
    })
    
    if verbose:
        print(f"\n{'='*60}")
        print("Processing Complete")
        print(f"{'='*60}\n")
        
        # Print final message
        final_message = result["messages"][-1]
        print(final_message.content)
    
    return result


def interactive_session(agent):
    """
    Run an interactive session with the agent.
    """
    print("\n" + "="*60)
    print("Environmental Report Assembly Assistant")
    print("="*60)
    print("\nCommands:")
    print("  - Enter a PDF path to process a report")
    print("  - Type 'quit' to exit")
    print("  - Type any message to chat with the agent")
    print()
    
    messages = []
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("\nGoodbye!")
                break
            
            if not user_input:
                continue
            
            messages.append(HumanMessage(content=user_input))
            
            result = agent.invoke({"messages": messages})
            
            # Get assistant response
            assistant_message = result["messages"][-1]
            messages = result["messages"]
            
            print(f"\nAssistant: {assistant_message.content}")
            
        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="ESA Report Assembly Agent")
    parser.add_argument("--pdf", type=str, help="Path to PDF file to process")
    parser.add_argument("--interactive", "-i", action="store_true", help="Run interactive session")
    parser.add_argument("--model", type=str, default="claude-sonnet-4-20250514", help="Model to use")
    
    args = parser.parse_args()
    
    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("Set it with: export ANTHROPIC_API_KEY=your-key-here")
        return
    
    # LangSmith config (optional)
    if os.environ.get("LANGCHAIN_API_KEY"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = os.environ.get("LANGCHAIN_PROJECT", "esa-report-agent")
        print(f"LangSmith tracing enabled - Project: {os.environ['LANGCHAIN_PROJECT']}")
    else:
        print("LangSmith tracing disabled (no LANGCHAIN_API_KEY)")
    
    print(f"Using model: {args.model}")
    
    # Create agent
    agent = create_agent(args.model)
    
    if args.pdf:
        # Process single file
        process_report(agent, args.pdf)
    elif args.interactive:
        # Interactive mode
        interactive_session(agent)
    else:
        # Default to interactive
        interactive_session(agent)


if __name__ == "__main__":
    main()
