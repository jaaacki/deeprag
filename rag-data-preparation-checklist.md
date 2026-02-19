# RAG Data Preparation Checklist

A comprehensive guide to preparing document databases for RAG systems from various data sources.

---

## Quick Reference: Data Source → Preparation Steps

| Data Source | Format | Primary Steps | Scripts Needed |
|-------------|--------|---------------|----------------|
| Google Drive Docs | Native, PDF, DOCX | Export → OCR (if scanned) → Clean → Chunk | `gdrive-export.sh` |
| Scanned PDFs | Image-based PDF | OCR → Layout Analysis → Clean → Chunk | `ocr-pipeline.py` |
| Databases | SQL/NoSQL | Extract → Transform → Documentize → Chunk | `db-extract.py` |
| Web Pages | HTML | Scrape → Strip HTML → Clean → Chunk | `web-scraper.py` |
| Emails | PST, EML, MBOX | Export → Parse → Clean → Chunk | `email-parser.py` |
| Office Files | DOCX, PPTX, XLSX | Extract text → Preserve structure → Chunk | `office-extract.py` |
| Code Repos | Git | Clone → Parse code/docs → Chunk | `code-parser.py` |
| APIs/JSON | JSON, XML | Parse → Flatten → Documentize → Chunk | `json-flatten.py` |

---

## Phase 1: Inventory & Assessment

### 1.1 Catalog All Data Sources

| Step | Action | Command/Script | Output |
|------|--------|----------------|--------|
| 1.1.1 | List all Google Drive folders | `gdrive ls` | Folder inventory |
| 1.1.2 | Identify database connections | Document connection strings | DB schema map |
| 1.1.3 | Locate file shares/network drives | `find /mnt/share -type f` | File manifest |
| 1.1.4 | Catalog API endpoints | OpenAPI/Swagger docs | API inventory |
| 1.1.5 | Identify email archives | Locate PST/MBOX files | Email inventory |

### 1.2 Assess Data Quality

| Step | Action | Command/Script | Output |
|------|--------|----------------|--------|
| 1.2.1 | Count documents per source | `find . -type f \| wc -l` | Document counts |
| 1.2.2 | Check file formats distribution | `find . -type f \| sed 's/.*\.//' \| sort \| uniq -c` | Format breakdown |
| 1.2.3 | Identify scanned vs digital PDFs | See script below | Scan ratio |
| 1.2.4 | Estimate total text volume | See script below | Token estimate |
| 1.2.5 | Check for duplicates | `fdupes -r ./data` | Duplicate report |

```bash
# Check PDF scan ratio (sample)
#!/bin/bash
# pdf-scanner-check.sh
total=0
scanned=0
for pdf in *.pdf; do
  total=$((total + 1))
  # Check if PDF has text layer
  if ! pdftotext "$pdf" - | grep -q .; then
    scanned=$((scanned + 1))
  fi
done
echo "Total: $total, Scanned: $scanned, Ratio: $(echo "scale=2; $scanned/$total*100" | bc)%"
```

---

## Phase 2: Source-Specific Extraction

### 2.1 Google Drive

| Step | Action | Script | Notes |
|------|--------|--------|-------|
| 2.1.1 | Authenticate | `gauth` | OAuth setup |
| 2.1.2 | Export Docs to PDF/Markdown | See below | Preserves formatting |
| 2.1.3 | Export Sheets to CSV | See below | One CSV per tab |
| 2.1.4 | Download existing files | `gdrive download` | Recursive |
| 2.1.5 | Organize by folder structure | Script preserves paths | Maintain context |

```bash
# gdrive-export.sh
#!/bin/bash
export GOOGLE_APPLICATION_CREDENTIALS="path/to/creds.json"

# Export Google Docs to PDF
gdrive export --mime-type application/pdf <file_id>

# Export Google Sheets to CSV  
gdrive export --mime-type text/csv <file_id>

# Export Google Slides to PDF
gdrive export --mime-type application/pdf <file_id>
```

### 2.2 Scanned PDFs & Images

| Step | Action | Script | Notes |
|------|--------|--------|-------|
| 2.2.1 | Run OCR | See below | Tesseract/PaddleOCR |
| 2.2.2 | Detect layout/regions | LayoutParser | Tables, figures |
| 2.2.3 | Extract tables | Tabula/Camelot | Structured data |
| 2.2.4 | Merge text with layout | Custom script | Preserve order |
| 2.2.5 | Quality check OCR | Confidence scores | Flag low-quality |

```python
# ocr-pipeline.py
import pytesseract
from pdf2image import convert_from_path
import layoutparser as lp

def ocr_pdf(pdf_path):
    images = convert_from_path(pdf_path)
    text_blocks = []
    
    for img in images:
        # OCR
        text = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        # Layout detection
        layout_model = lp.Detectron2LayoutModel('lp://PubLayNet')
        layout = layout_model.detect(lp.load_image(img))
        # Combine with layout info
        text_blocks.append({'text': text, 'layout': layout})
    
    return text_blocks
```

### 2.3 Databases (SQL/NoSQL)

| Step | Action | Script | Notes |
|------|--------|--------|-------|
| 2.3.1 | Export schema | See below | Table relationships |
| 2.3.2 | Extract relevant tables | See below | Filter by relevance |
| 2.3.3 | Join related tables | SQL queries | Create documents |
| 2.3.4 | Handle BLOBs/attachments | Extract to files | Link in text |
| 2.3.5 | Export to JSONL | See below | One doc per line |

```python
# db-extract.py
import sqlite3
import json

def extract_to_documents(db_path, query):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    documents = []
    for row in cursor.execute(query):
        doc = {
            'id': row['id'],
            'content': f"Record: {dict(row)}",
            'metadata': {'source': 'database', 'table': '...'}
        }
        documents.append(doc)
    
    with open('output.jsonl', 'w') as f:
        for doc in documents:
            f.write(json.dumps(doc) + '\n')
```

### 2.4 Office Documents (DOCX, PPTX, XLSX)

| Step | Action | Script | Notes |
|------|--------|--------|-------|
| 2.4.1 | Extract DOCX text + structure | See below | Preserve headings |
| 2.4.2 | Extract PPTX slides | See below | One section per slide |
| 2.4.3 | Extract XLSX as tables | See below | CSV + description |
| 2.4.4 | Preserve metadata | Created, author, etc. | For filtering |
| 2.4.5 | Handle embedded objects | Extract separately | Images, charts |

```python
# office-extract.py
from docx import Document
from pptx import Presentation
import openpyxl
import json

def extract_docx(path):
    doc = Document(path)
    content = []
    for para in doc.paragraphs:
        content.append({
            'type': 'paragraph' if para.style.name.startswith('Normal') else 'heading',
            'text': para.text
        })
    return content

def extract_pptx(path):
    prs = Presentation(path)
    slides = []
    for slide in prs.slides:
        slide_text = '\n'.join([shape.text for shape in slide.shapes if hasattr(shape, 'text')])
        slides.append(slide_text)
    return slides
```

### 2.5 Emails (PST, EML, MBOX)

| Step | Action | Script | Notes |
|------|--------|--------|-------|
| 2.5.1 | Convert PST to MBOX | `libpst` tools | Outlook compatibility |
| 2.5.2 | Parse email headers | See below | From, to, date, subject |
| 2.5.3 | Extract attachments | Save separately | Link in document |
| 2.5.4 | Thread reconstruction | Group by In-Reply-To | Conversation context |
| 2.5.5 | Handle HTML emails | Strip to text | Preserve links |

```python
# email-parser.py
import mailbox
import email
from email import policy
import json

def parse_mbox(path):
    mbox = mailbox.mbox(path)
    documents = []
    
    for message in mbox:
        doc = {
            'id': message['Message-ID'],
            'from': message['From'],
            'to': message['To'],
            'date': message['Date'],
            'subject': message['Subject'],
            'content': '',
            'attachments': []
        }
        
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_type() == 'text/plain':
                    doc['content'] += part.get_payload(decode=True).decode()
                elif part.get_content_disposition() == 'attachment':
                    doc['attachments'].append(part.get_filename())
        else:
            doc['content'] = message.get_payload(decode=True).decode()
        
        documents.append(doc)
    
    return documents
```

### 2.6 Web Pages & APIs

| Step | Action | Script | Notes |
|------|--------|--------|-------|
| 2.6.1 | Crawl sitemap | See below | Respect robots.txt |
| 2.6.2 | Extract main content | Readability | Remove nav/ads |
| 2.6.3 | Handle pagination | Follow next links | Complete articles |
| 2.6.4 | Extract API docs | OpenAPI parser | Auto-generate docs |
| 2.6.5 | Preserve URL structure | Breadcrumb context | For chunk metadata |

```python
# web-scraper.py
import requests
from readability import Document
from bs4 import BeautifulSoup

def scrape_page(url):
    response = requests.get(url)
    doc = Document(response.text)
    
    return {
        'url': url,
        'title': doc.title(),
        'content': doc.summary(),
        'text': doc.text_content()
    }
```

---

## Phase 3: Text Cleaning & Normalization

### 3.1 Universal Cleaning Steps

| Step | Action | Script | Notes |
|------|--------|--------|-------|
| 3.1.1 | Remove boilerplate | See below | Headers, footers |
| 3.1.2 | Normalize whitespace | Regex cleanup | Consistent spacing |
| 3.1.3 | Fix encoding issues | `ftfy` library | Unicode cleanup |
| 3.1.4 | Remove PII | Presidio/regex | GDPR compliance |
| 3.1.5 | Deduplicate | Fuzzy matching | Near-duplicates |

```python
# text-cleaner.py
import re
import ftfy
from presidio_analyzer import AnalyzerEngine

def clean_text(text):
    # Fix encoding
    text = ftfy.fix_text(text)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    # Remove common boilerplate patterns
    text = re.sub(r'Page \d+ of \d+', '', text)
    text = re.sub(r'Confidential.*', '', text)
    
    # PII detection (example)
    analyzer = AnalyzerEngine()
    results = analyzer.analyze(text=text, language='en')
    # Handle PII results based on policy
    
    return text
```

---

## Phase 4: Document Structuring & Chunking

### 4.1 Chunking Strategy by Data Type

| Data Type | Chunk Size | Overlap | Strategy |
|-----------|------------|---------|----------|
| Technical docs | 512-1024 tokens | 50-100 | By section/heading |
| Legal contracts | 256-512 tokens | 25-50 | By clause |
| Emails | 256 tokens | 0 | By message |
| Database records | N/A | N/A | One doc per record |
| Code files | 512 tokens | 50 | By function/class |
| Tables | N/A | N/A | Keep table intact |
| Q&A pairs | 128-256 tokens | 0 | By Q&A unit |

### 4.2 Chunking Implementation

```python
# chunker.py
from langchain.text_splitter import (
    RecursiveCharacterTextSplitter,
    MarkdownTextSplitter,
    PythonCodeTextSplitter
)

def chunk_document(text, doc_type='general'):
    if doc_type == 'markdown':
        splitter = MarkdownTextSplitter(chunk_size=512, chunk_overlap=50)
    elif doc_type == 'code':
        splitter = PythonCodeTextSplitter(chunk_size=512, chunk_overlap=50)
    else:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=512,
            chunk_overlap=50,
            separators=['\n## ', '\n### ', '\n', '. ', ' ']
        )
    
    return splitter.split_text(text)
```

---

## Phase 5: Metadata & Indexing

### 5.1 Metadata Schema

| Field | Type | Required | Source |
|-------|------|----------|--------|
| `doc_id` | string | Yes | Generated UUID |
| `source` | string | Yes | Original source |
| `source_path` | string | Yes | File path/URL |
| `chunk_id` | integer | Yes | Chunk sequence |
| `total_chunks` | integer | Yes | For reassembly |
| `created_date` | datetime | No | File metadata |
| `modified_date` | datetime | No | File metadata |
| `author` | string | No | Extracted |
| `doc_type` | enum | Yes | Classification |
| `language` | string | Yes | Detected |
| `tags` | array | No | Extracted/assigned |

### 5.2 Metadata Extraction Script

```python
# metadata-extractor.py
import os
import hashlib
from datetime import datetime
import langdetect

def extract_metadata(file_path, chunk_id=0):
    stat = os.stat(file_path)
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    return {
        'doc_id': hashlib.md5(f"{file_path}:{chunk_id}".encode()).hexdigest(),
        'source': os.path.basename(file_path),
        'source_path': file_path,
        'chunk_id': chunk_id,
        'created_date': datetime.fromtimestamp(stat.st_ctime).isoformat(),
        'modified_date': datetime.fromtimestamp(stat.st_mtime).isoformat(),
        'language': langdetect.detect(content[:1000]),
        'file_size': stat.st_size
    }
```

---

## Phase 6: Quality Assurance

### 6.1 QA Checklist

| Check | Method | Threshold | Action if Failed |
|-------|--------|-----------|------------------|
| Text extraction complete | Char count > 0 | 100% | Re-extract |
| OCR accuracy | Word error rate | < 5% | Manual review |
| No PII leakage | Presidio scan | 0% | Redact/remove |
| Chunk size distribution | Histogram | Within bounds | Re-chunk |
| Metadata completeness | Null check | > 95% | Backfill |
| No duplicates | Dedup scan | 0% | Remove |
| Encoding valid | UTF-8 validate | 100% | Re-encode |

### 6.2 QA Script

```python
# qa-check.py
import json
from collections import Counter

def qa_report(documents):
    issues = []
    
    # Check for empty documents
    empty_docs = [i for i, d in enumerate(documents) if not d.get('content', '').strip()]
    if empty_docs:
        issues.append(f"Empty documents: {len(empty_docs)}")
    
    # Check chunk sizes
    sizes = [len(d.get('content', '')) for d in documents]
    if sizes:
        avg_size = sum(sizes) / len(sizes)
        outliers = [i for i, s in enumerate(sizes) if abs(s - avg_size) > avg_size * 2]
        if outliers:
            issues.append(f"Size outliers: {len(outliers)}")
    
    # Check metadata completeness
    required_fields = ['doc_id', 'source', 'source_path']
    for i, doc in enumerate(documents):
        missing = [f for f in required_fields if f not in doc.get('metadata', {})]
        if missing:
            issues.append(f"Doc {i}: Missing metadata {missing}")
    
    return {
        'total_docs': len(documents),
        'issues': issues,
        'passed': len(issues) == 0
    }
```

---

## Phase 7: Storage Preparation

### 7.1 Output Format Options

| Format | Use Case | Pros | Cons |
|--------|----------|------|------|
| JSONL | General | Streamable, simple | No schema enforcement |
| Parquet | Large datasets | Compressed, fast | Binary format |
| SQLite | Small-medium | Queryable, portable | Single writer |
| NDJSON | Streaming | Line-delimited | Same as JSONL |

### 7.2 Final Export Script

```python
# export-final.py
import json
import pandas as pd

def export_documents(documents, output_path, format='jsonl'):
    if format == 'jsonl':
        with open(output_path, 'w') as f:
            for doc in documents:
                f.write(json.dumps(doc) + '\n')
    
    elif format == 'parquet':
        df = pd.DataFrame(documents)
        df.to_parquet(output_path, index=False)
    
    elif format == 'sqlite':
        import sqlite3
        conn = sqlite3.connect(output_path)
        df = pd.DataFrame(documents)
        df.to_sql('documents', conn, index=False)
```

---

## Quick Start: Minimal Pipeline

For a simple start, run these steps in order:

```bash
# 1. Create project structure
mkdir -p rag-data/{raw,processed,chunks,output}

# 2. Copy all source files to raw/
cp -r /path/to/sources/* rag-data/raw/

# 3. Extract text from all PDFs
for f in rag-data/raw/*.pdf; do
  pdftotext "$f" "rag-data/processed/$(basename $f .pdf).txt"
done

# 4. Run basic cleaning
for f in rag-data/processed/*.txt; do
  sed -E 's/\s+/ /g' "$f" | \
  sed -E 's/Page [0-9]+//g' > "rag-data/cleaned/$(basename $f)"
done

# 5. Chunk (using Python)
python chunker.py rag-data/cleaned/ rag-data/chunks/

# 6. Add metadata and export
python metadata-extractor.py rag-data/chunks/ rag-data/output/documents.jsonl
```

---

## Summary: Pre-RAG Readiness Checklist

- [ ] **Inventory complete**: All sources cataloged
- [ ] **Quality assessed**: Known issues documented
- [ ] **Extraction done**: All text extracted with >95% accuracy
- [ ] **Cleaning complete**: PII removed, encoding fixed
- [ ] **Chunking done**: Consistent chunk sizes
- [ ] **Metadata added**: Schema compliance >95%
- [ ] **Duplicates removed**: No exact or near-duplicates
- [ ] **QA passed**: All checks green
- [ ] **Export complete**: Ready for vector store
