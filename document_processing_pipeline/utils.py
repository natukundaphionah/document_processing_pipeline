import os
import shutil
import re
import time
import getpass
from pathlib import Path
from dotenv import load_dotenv

from mistralai import Mistral
from mistralai import DocumentURLChunk, ImageURLChunk, OCRResponse

# -----------------------------
# LOAD ENVIRONMENT VARIABLES
# -----------------------------
# This loads environment variables from a .env file into your script.
# Use this for secure storage of API keys.
load_dotenv()


# -----------------------------
# SECURE API KEY FUNCTIONS
# -----------------------------
def get_api_key() -> str:
    """
    Retrieves the Mistral API key securely.
    Priority:
        1. From environment variable MISTRAL_API_KEY
        2. Fallback to manual input via getpass
    """
    key = os.getenv("MISTRAL_API_KEY")
    if key:
        return key

    # If not found in environment, ask user to input it securely
    return getpass.getpass("Enter Mistral API Key: ")


def get_client() -> Mistral:
    """
    Creates and returns a Mistral API client using the secure API key.
    """
    api_key = get_api_key()
    return Mistral(api_key=api_key)


# FILE MANAGEMENT FUNCTIONS
def get_pdf_files_in_directory(base_path: str) -> list[str]:
    """
    Returns a list of all PDF files in a given directory.
    """
    pdf_files = []

    if not os.path.exists(base_path) or not os.path.isdir(base_path):
        print(f"Warning: The path '{base_path}' does not exist or is not a directory.")
        return []

    for item in os.listdir(base_path):
        full_path = os.path.join(base_path, item)
        if os.path.isfile(full_path) and item.lower().endswith(".pdf"):
            pdf_files.append(full_path)

    return pdf_files


# -----------------------------
# OCR FUNCTIONS
# -----------------------------
def extract_text_from_image(base64_image: str) -> str:
    """
    Extracts text from a base64 image using Mistral OCR.
    Returns the OCR'd text as markdown.
    """
    client = get_client()
    base64_data_url = f"data:image/jpeg;base64,{base64_image}"

    image_response = client.ocr.process(
        document=ImageURLChunk(image_url=base64_data_url),
        model="mistral-ocr-latest"
    )

    return image_response.pages[0].markdown.strip()


def replace_images_with_text(markdown_str: str, images: list) -> str:
    """
    Replaces image placeholders in markdown with OCR'd text.
    If OCR fails, removes the placeholder.
    """
    for img in images:
        try:
            image_text = extract_text_from_image(img.image_base64)
            if image_text:
                markdown_str = markdown_str.replace(f"![{img.id}]({img.id})", f"\n\n{image_text}\n\n")
            else:
                markdown_str = markdown_str.replace(f"![{img.id}]({img.id})", "")
        except Exception:
            # Remove image if OCR fails
            markdown_str = markdown_str.replace(f"![{img.id}]({img.id})", "")
    return markdown_str


def get_combined_markdown(ocr_response:OCRResponse) -> str:
    """
    Combines all pages of OCR markdown into a single markdown string.
    """
    markdown_pages = []
    for page in ocr_response.pages:
        page_markdown = replace_images_with_text(page.markdown, page.images)
        markdown_pages.append(page_markdown)
    return "\n\n".join(markdown_pages)


# -----------------------------
# CLEANING FUNCTIONS
# -----------------------------
def remove_chinese_phrase(text: str) -> str:
    """Removes a specific repeated Chinese phrase often present in OCR results."""
    pattern = r"哈，你是个小伙子(，你是个小伙子)*"
    return re.sub(pattern, "", text)


def remove_image_urls(text: str) -> str:
    """Removes any markdown image links."""
    return re.sub(r"!\[.*?\]\(.*?\)", "", text)


import re

def remove_table_of_contents(text: str) -> str:
    """
    Removes table of contents sections from OCR/markdown documents.
    """

    patterns = [
        r"\n\s*#*\s*\d*\.?\s*Table of Contents\s*\n.*?(?=\n\s*#|\Z)",
        r"\n\s*#*\s*\d*\.?\s*Contents\s*\n.*?(?=\n\s*#|\Z)",
        r"\n\s*TABLE OF CONTENTS\s*\n.*?(?=\n[A-Z][^\n]{0,80}\n|\Z)",
        r"\n\s*CONTENTS\s*\n.*?(?=\n[A-Z][^\n]{0,80}\n|\Z)"
    ]

    for pattern in patterns:
        text = re.sub(pattern, "\n", text, flags=re.IGNORECASE | re.DOTALL)

    return text
import re

def remove_dotted_toc(text: str) -> str:
    """
    Removes lines that look like table of contents with dots and page numbers.
    Example lines removed:
        NYUTE...10
        SPECIAL ACKNOWLEDGEMENT...12
        DEDICATION...13
    Keeps normal text intact.
    """
    pattern = r"(?m)^\s*[A-Z0-9\s/&-]+\.{2,}\d+\s*$"
    pattern = r"^[A-Z][A-Z\s—\-']+\.{2,}\d+\s*$"
    return re.sub(pattern, "", text, flags=re.MULTILINE)
    # Explanation:
    # (?m)              => multiline mode (^ and $ match each line)
    # ^\s*              => start of line, optional spaces
    # [A-Z0-9\s/&-]+    => heading text (capital letters, numbers, spaces, /, &, -)
    # \.{2,}            => two or more dots
    # \d+               => page number
    # \s*$              => optional spaces until line end

    return re.sub(pattern, "", text).strip()

def remove_acknowledgements(text: str) -> str:
    """
    Removes all Acknowledgements sections, including:
    - Acknowledgement(s)
    - SPECIAL ACKNOWLEDGEMENT(S)
    - ACKNOWLEDGEMENTS AND THANKS
    - Markdown headings (#, ##) or numbered headings (1., IV.)
    """

    pattern = r"""
    (?im)                                   # case-insensitive + multiline
    ^\s*                                    # start of line
    (?:\#{1,6}\s*|[\divxlc]+\.\s*)?        # optional markdown # or numbering/roman numeral
    (?:                                     # match any of the acknowledgement variants
        Acknowledg(?:e)?ments? |
        Special\s+Acknowledg(?:e)?ments? |
        Acknowledg(?:e)?ments?\s+and\s+Thanks
    )
    \s*\n                                   # end of heading line
    .*?                                     # section content (non-greedy)
    (?=^\s*(?:\#{1,6}\s*|[\divxlc]+\.\s*)|\Z)  # stop at next heading or end of text
    """

    return re.sub(pattern, "\n", text, flags=re.DOTALL | re.VERBOSE)

def remove_front_matter(text: str) -> str:
    """
    Removes Preface, Foreword, Dedication, Acknowledgements,
    and Conclusion sections wherever they appear in the document.
    Works with markdown headings and numbered headings.
    """

    pattern = r"""
    \n\s*                # new line
    \#*\s*               # optional markdown #
    \d*\.?\s*            # optional number like '5.' or '6'
    (Preface|Foreword|Dedication|Acknowledg(e)?ments?|Conclusion(s)?) 
    \s*\n                # end of heading
    .*?                  # section content
    (?=\n\s*\#*\s*\d*\.?\s*[A-Z][^\n]{0,80}\n|\Z)  # stop at next heading
    """

    return re.sub(pattern, "\n", text, flags=re.IGNORECASE | re.DOTALL | re.VERBOSE)


def remove_authors_contributors(text: str) -> str:
    """
    Removes author and contributor sections robustly.
    Matches lines starting with By:, Author(s):, Contributors:, and all their following lines
    until the next heading or empty line.
    """
    patterns = [
        r"\nBy:.*?(?=\n#|\n[A-Z]|$)",  # everything after 'By:' until heading, uppercase line, or end
        r"\nAuthors?:.*?(?=\n#|\n[A-Z]|$)",
        r"\nContributors?:.*?(?=\n#|\n[A-Z]|$)"
    ]
    for pattern in patterns:
        text = re.sub(pattern, "\n", text, flags=re.IGNORECASE | re.DOTALL)

    return text.strip()

import re


import re
from collections import Counter

def remove_footnotes(text: str) -> str:
    lines = text.splitlines()

    # Count frequency of each line (to detect repeated headers/footers)
    line_counts = Counter(line.strip() for line in lines if line.strip())

    cleaned_lines = []
    total_lines = len(lines)

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            continue

        # 1. Remove lines that repeat frequently (likely headers/footers)
        if line_counts[stripped] > 2:
            continue

        # 2. Remove lines that are just numbers (page numbers)
        if re.fullmatch(r"\d+", stripped):
            continue

        # 3. Remove short lines at the bottom of pages (likely footers)
        # Heuristic: short + near end of a block
        if len(stripped) < 50 and re.search(r"\d$", stripped):
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def remove_publications_section(text: str) -> str:
    """Removes any publications list."""
    patterns = [
        r"\n#+\s*List of Publications.*?(?=\n#+|\Z)",
        r"\nPUBLICATIONS.*?(?=\n#+|\Z)"
    ]
    for pattern in patterns:
        text = re.sub(pattern, "\n", text, flags=re.IGNORECASE | re.DOTALL)
    return text


def remove_references_section(text: str) -> str:
    """
    Removes references, bibliography, works cited, etc.
    Cuts everything from the reference title to the end of the document.
    """

    pattern = r'(^|\n)\s*(#+\s*)?(\d+\.?\s*)?(References|Bibliography|Works\s*Cited|Literature\s*Cited)\s*[:\n].*'

    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)

    if match:
        return text[:match.start()].strip()

    return text


def remove_index_section(text: str) -> str:
    """Removes index sections."""
    patterns = [
        r"\n#+\s*Index\s*\n.*",
        r"\nINDEX\s*\n.*"
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return text[:match.start()].strip()
    return text


import re

def remove_list_of_entries(text: str) -> str:
    """Removes list sections such as List of Entries, Abbreviations, Figures, Tables, and Illustrations."""

    patterns = [
        # Numbered headings (1., iv., etc.)
        r"\n(?:[ivxlcdmIVXLCDM]+|\d+)\.?\s*List of (Entries|Abbreviations|Figures|Tables|Illustrations).*?(?=\n#+|\Z)",

        # Markdown headings with optional numbering
        r"\n#+\s*\d*\.?\s*List of (Entries|Abbreviations|Figures|Tables|Illustrations).*?(?=\n#+|\Z)",

        # Plain headings
        r"\nList of (Entries|Abbreviations|Figures|Tables|Illustrations).*?(?=\n[A-Z][^\n]{0,80}\n|\Z)",

        # Cases where it is just "Abbreviations"
        r"\n#+\s*\d*\.?\s*Abbreviations\s*\n.*?(?=\n#+|\Z)",
        r"\nAbbreviations\s*\n.*?(?=\n[A-Z][^\n]{0,80}\n|\Z)"
    ]

    for pattern in patterns:
        text = re.sub(pattern, "\n", text, flags=re.IGNORECASE | re.DOTALL)

    return text

def remove_list_of_images_maps(text: str) -> str:
    """Removes lists of images or maps in markdown."""
    patterns = [
        r"\n#+\s*List of Images.*?(?=\n#+|\Z)",
        r"\nList of Images.*?(?=\n[A-Z][^\n]{0,80}\n|\Z)",
        r"\n#+\s*List of Maps.*?(?=\n#+|\Z)",
        r"\nList of Maps.*?(?=\n[A-Z][^\n]{0,80}\n|\Z)"
    ]
    for pattern in patterns:
        text = re.sub(pattern, "\n", text, flags=re.IGNORECASE | re.DOTALL)
    return text

import re

def remove_unwanted_sections(text: str) -> str:
    """
    Removes specific sections like Abbreviations, Tables, Figures, Notes, and Conclusions.
    """

    patterns = [
        r"\n#+\s*Abbreviations and conventional signs.*?(?=\n#+|\Z)",
        r"\n#+\s*Tables.*?(?=\n#+|\Z)",
        r"\n#+\s*Figures.*?(?=\n#+|\Z)",
        r"\n#+\s*Notes.*?(?=\n#+|\Z)",
        r"\n#+\s*CONCLUSIONS.*?(?=\n#+|\Z)"
    ]

    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)

    return text.strip()

import re

def remove_preface(text: str) -> str:
    """
    Removes Preface sections in all variations:
    - PREFACE
    - Preface IN ENGLISH
    - # PREFACE
    - ## Preface
    - 1. Preface
    - Preface (any extra words after it)
    """

    pattern = r"""
    (?im)                          # ignore case + multiline

    ^\s*                           # start of line
    (\#*\s*|\d+\.?\s*)?           # optional markdown or numbering
    PREFACE                       # main keyword
    [^\n]*                        # anything after (e.g. IN ENGLISH)
    \n                            # end of heading line

    .*?                           # content of Preface

    (?=^\s*(\#|\d+\.|\w))         # stop at next section heading
    """

    return re.sub(pattern, "\n", text, flags=re.DOTALL | re.IGNORECASE | re.VERBOSE | re.MULTILINE)

def remove_alphabetical_entries(text: str) -> str:
    """
    Removes glossary or A-Z alphabetical sections from the text.
    Looks for headings like 'Entries A–Z', 'Glossary', or 'A', 'B', 'C' as start of an alphabetical section.
    """
    # Patterns to detect alphabetical sections
    patterns = [
        r"\nEntries\s*A–Z.*",  # Matches 'Entries A–Z'
        r"\nGlossary.*",        # Matches 'Glossary'
        # r"\n[A-Z]\s*\n"         # Matches single capital letters on their own line (like glossary headings)
    ]

    earliest_match = None
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and (earliest_match is None or match.start() < earliest_match.start()):
            earliest_match = match

    if earliest_match:
        # Keep everything before the alphabetical section
        return text[:earliest_match.start()].strip()
    return text.strip()

def start_from_abstract_or_intro(text: str) -> str:
    """
    Starts the text from Abstract or Introduction if available.
    This helps remove preambles, acknowledgements, or front matter.
    """
    match = re.search(
        r"(^|\n)(#*\s*)?(\d+\.\d+\s*)?(Abstract|Introduction|ABSTRACT|INTRODUCTION)[:\s]*\n",
        text,
        re.IGNORECASE
    )
    if match:
        return text[match.start():].strip()
    return text


def clean_markdown_pipeline(text: str) -> str:
    """
    Full cleaning pipeline:
    1. Remove repeated Chinese phrases
    2. Remove image URLs
    3. Remove table of contents and front matter
    4. Remove authors/contributors
    5. Start from Abstract/Introduction
    6. Remove footnotes, publications, references, index
    7. Remove lists and alphabetical sections
    """
    text = remove_chinese_phrase(text)
    text = remove_image_urls(text)
    text = remove_table_of_contents(text)
    text = remove_front_matter(text)
    text = remove_preface(text)
    text = remove_acknowledgements(text)
    text = remove_dotted_toc(text)
    text = remove_authors_contributors(text)
    text = remove_unwanted_sections(text)
    text = start_from_abstract_or_intro(text)
    text = remove_footnotes(text)
    text = remove_publications_section(text)
    text = remove_references_section(text)
    text = remove_index_section(text)
    text = remove_list_of_entries(text)
    text = remove_alphabetical_entries(text)
    text = remove_list_of_images_maps(text)

    return text.strip()