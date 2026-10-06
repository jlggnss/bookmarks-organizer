#!/usr/bin/env python3
"""Bookmarks Organizer - Organize browser bookmarks using AI (Gemini or OpenAI) with Excel support."""

import argparse
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
import os

from src.parser import parse_bookmarks, extract_all_bookmarks, extract_uncategorized_bookmarks
from src.organizer import organize_bookmarks, build_organized_tree
from src.writer import write_bookmarks
from src.progress import get_progress_path, load_progress, clear_progress
from src.llm_factory import create_llm_client
from src.excel import export_bookmarks_to_excel, import_bookmarks_from_excel


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Organize browser bookmarks into categories using AI (Gemini or OpenAI) or manage via Excel.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Standard AI Organization (Gemini or OpenAI):
  python main.py bookmarks.html
  python main.py bookmarks.html --provider gemini --model gemini-3.8-flash
  python main.py bookmarks.html -o organized.html
  python main.py bookmarks.html --preserve-toolbar

  # Excel Workflow (Clean in Excel before/after AI):
  python main.py bookmarks.html --to-excel bookmarks.xlsx
  python main.py bookmarks.xlsx -o bookmarks_cleaned.html --no-ai
  python main.py bookmarks.xlsx -o bookmarks_organized.html --provider gemini
  python main.py bookmarks.html -o bookmarks_organized.xlsx
""",
    )
    parser.add_argument("input", help="Path to input bookmarks file (.html or .xlsx)")
    parser.add_argument("-o", "--output", default=None, help="Output file path (.html or .xlsx)")
    parser.add_argument("--to-excel", nargs="?", const="bookmarks.xlsx", default=None, help="Export input to an Excel spreadsheet (.xlsx) for manual cleanup")
    parser.add_argument("--from-excel", nargs="?", const="bookmarks.html", default=None, help="Convert an Excel spreadsheet back to Netscape HTML format")
    parser.add_argument("--no-ai", action="store_true", help="Skip AI categorization and just convert formats between HTML and Excel")
    parser.add_argument("--preserve-toolbar", action="store_true", help="Keep bookmarks placed directly on the Bookmarks Bar intact (preserves shortened titles)")
    parser.add_argument("--uncategorized-only", action="store_true", help="Only sort bookmarks in the 'Uncategorized' folder")
    parser.add_argument("--provider", choices=["auto", "gemini", "openai"], default=None, help="LLM provider: gemini or openai (default: auto-detected)")
    parser.add_argument("--model", default=None, help="Model to use (overrides .env and config)")
    parser.add_argument("--base-url", default=None, help="API base URL for OpenAI-compatible providers (overrides .env)")
    parser.add_argument("--api-key", default=None, help="API key (overrides .env)")
    parser.add_argument("--max-categories", type=int, default=None, help="Max categories to create")
    parser.add_argument("--batch-size", type=int, default=None, help="Bookmarks per LLM batch")
    parser.add_argument("--no-resume", action="store_true", help="Ignore saved progress and start fresh")

    args = parser.parse_args()

    # Load config
    config = {}
    config_path = Path(__file__).parent / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    max_categories = args.max_categories or config.get("max_categories", 20)
    batch_size = args.batch_size or config.get("batch_size", 10)
    protected_folders = config.get("protected_folders", [])
    preserve_toolbar = args.preserve_toolbar or config.get("preserve_toolbar", False)
    root_folder = config.get("root_folder", "Bookmarks bar")

    # Parse suggested_categories from config (supports list or comma-separated string)
    suggested_raw = config.get("suggested_categories", [])
    if isinstance(suggested_raw, str):
        suggested_list = [c.strip().strip("`").strip("'").strip('"') for c in suggested_raw.split(",") if c.strip()]
    elif isinstance(suggested_raw, list):
        suggested_list = [str(c).strip().strip("`").strip("'").strip('"') for c in suggested_raw if str(c).strip()]
    else:
        suggested_list = []
    
    suggested_categories = []
    for sc in suggested_list:
        clean = sc.rstrip("/*").rstrip("/*").strip()
        if clean and clean not in suggested_categories:
            suggested_categories.append(clean)

    # Read input file
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        sys.exit(1)

    # Determine input type
    is_input_excel = input_path.suffix.lower() in (".xlsx", ".xlsm")

    print(f"Reading bookmarks from: {input_path}")
    if is_input_excel:
        root = import_bookmarks_from_excel(input_path)
    else:
        html_content = input_path.read_text(encoding="utf-8")
        root = parse_bookmarks(html_content)

    # Quick export to Excel (--to-excel)
    if args.to_excel:
        excel_out = Path(args.to_excel)
        export_bookmarks_to_excel(root, excel_out)
        print(f"Successfully exported bookmarks to Excel: {excel_out}")
        print("Open in Excel to review, sort by date, filter domains, or delete unwanted links.")
        sys.exit(0)

    # Quick export from Excel (--from-excel)
    if args.from_excel:
        html_out = Path(args.from_excel)
        output_html = write_bookmarks(root)
        html_out.write_text(output_html, encoding="utf-8")
        print(f"Successfully converted Excel bookmarks to HTML: {html_out}")
        sys.exit(0)

    # Determine default output file
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path("bookmarks_organized.xlsx" if is_input_excel and not args.no_ai else "bookmarks_organized.html")

    is_output_excel = output_path.suffix.lower() in (".xlsx", ".xlsm")

    # If --no-ai is specified, just write the parsed tree directly to output
    if args.no_ai:
        if is_output_excel:
            export_bookmarks_to_excel(root, output_path)
            print(f"Saved bookmarks to Excel (without AI): {output_path}")
        else:
            output_html = write_bookmarks(root)
            output_path.write_text(output_html, encoding="utf-8")
            print(f"Saved bookmarks to HTML (without AI): {output_path}")
        sys.exit(0)

    # Initialize LLM client for AI categorization
    try:
        client, provider, model = create_llm_client(
            provider=args.provider or config.get("provider"),
            api_key=args.api_key,
            model=args.model or config.get("model"),
            base_url=args.base_url,
        )
    except ValueError as e:
        print(f"Error: {e}")
        print("Set GEMINI_API_KEY or API_KEY in .env, or pass --api-key.")
        print("(Hint: Use --no-ai or --to-excel to convert between HTML and Excel without an API key)")
        sys.exit(1)

    # Extract bookmarks based on mode
    if args.uncategorized_only:
        print("Mode: Organizing uncategorized bookmarks only")
        bookmarks, kept_folders = extract_uncategorized_bookmarks(root, protected_folders)
        existing_categories = [f.title for f in kept_folders]
    else:
        print("Mode: Organizing all bookmarks")
        if preserve_toolbar:
            print("Toolbar Preservation: Direct bookmarks on 'Bookmarks bar' will be kept intact")
        bookmarks, kept_folders = extract_all_bookmarks(
            root,
            protected_folders,
            preserve_toolbar=preserve_toolbar,
        )
        existing_categories = []

    if not bookmarks:
        print("No bookmarks to organize.")
        sys.exit(0)

    print(f"Found {len(bookmarks)} bookmarks to organize")
    if kept_folders:
        print(f"Protected/Preserved folders: {[f.title for f in kept_folders]}")
    print(f"Provider: {provider}")
    print(f"Using model: {model}")
    if provider == "openai":
        base_url = getattr(client, "base_url", "https://api.openai.com/v1")
        print(f"API base: {base_url}")
    print()

    # Check for saved progress
    progress_path = get_progress_path(str(output_path))
    start_index = 0
    resumed_categories = None

    if not args.no_resume:
        progress = load_progress(progress_path)
        if progress and progress["total_count"] == len(bookmarks):
            already_done = len(bookmarks) - len(progress["remaining_indices"])
            print(f"Found saved progress: {already_done}/{len(bookmarks)} bookmarks already categorized.")
            print("Resuming... (use --no-resume to start fresh)\n")
            start_index = already_done
            resumed_categories = progress["categories"]
        elif progress:
            print("Found saved progress but bookmark count changed. Starting fresh.\n")
            clear_progress(progress_path)
    else:
        clear_progress(progress_path)

    # Organize bookmarks (with graceful interrupt handling)
    print("Categorizing bookmarks...")
    try:
        categories = organize_bookmarks(
            bookmarks=bookmarks,
            client=client,
            model=model,
            max_categories=max_categories,
            batch_size=batch_size,
            existing_categories=existing_categories,
            suggested_categories=suggested_categories,
            progress_path=progress_path,
            start_index=start_index,
            resumed_categories=resumed_categories,
        )
    except KeyboardInterrupt:
        print("\n\nInterrupted! Progress has been saved.")
        print("Run the same command again to resume, or use --no-resume to start over.")
        sys.exit(130)

    print(f"\nCreated {len(categories)} categories:")
    for cat, bms in sorted(categories.items()):
        print(f"  {cat}: {len(bms)} bookmarks")

    # Build output tree
    organized = build_organized_tree(
        categories=categories,
        protected_folders=kept_folders,
        root_folder_name=root_folder,
    )

    # Write output (HTML or Excel depending on extension)
    if is_output_excel:
        export_bookmarks_to_excel(organized, output_path)
    else:
        output_html = write_bookmarks(organized)
        output_path.write_text(output_html, encoding="utf-8")

    # Clean up progress file on success
    clear_progress(progress_path)

    print(f"\nOrganized bookmarks written to: {output_path}")


if __name__ == "__main__":
    main()
