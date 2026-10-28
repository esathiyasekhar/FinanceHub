"""PDF opening, decryption, text extraction, and OCR utilities."""
import io
import re

try:
    import pdfplumber
    PDFPLUMBER_OK = True
except ImportError:
    PDFPLUMBER_OK = False

try:
    import pikepdf
    PIKEPDF_OK = True
except ImportError:
    PIKEPDF_OK = False

try:
    from pdf2image import convert_from_path, convert_from_bytes
    PDF2IMAGE_OK = True
except ImportError:
    PDF2IMAGE_OK = False

try:
    import pytesseract
    TESSERACT_OK = True
except ImportError:
    TESSERACT_OK = False


def is_password_protected(filepath: str) -> bool:
    """Return True if the PDF requires a password."""
    try:
        with pdfplumber.open(filepath) as pdf:
            _ = pdf.pages[0].extract_text()
        return False
    except Exception as e:
        if 'password' in str(e).lower() or 'encrypt' in str(e).lower():
            return True
        return False


def needs_password(filepath: str) -> bool:
    """True if the PDF cannot be opened without a password."""
    if PIKEPDF_OK:
        try:
            with pikepdf.Pdf.open(filepath):
                return False
        except pikepdf.PasswordError:
            return True
        except Exception:
            return False
    return is_password_protected(filepath)


def check_password(filepath: str, password: str) -> bool:
    """True if `password` opens the PDF (or the PDF has no password)."""
    if not PIKEPDF_OK:
        return True
    try:
        with pikepdf.Pdf.open(filepath, password=password or ''):
            return True
    except pikepdf.PasswordError:
        return False
    except Exception:
        return True


def open_pdf(filepath: str, password: str = ''):
    """
    Open PDF with pdfplumber. If password-protected, decrypt via pikepdf first.
    Returns a pdfplumber PDF object (context manager).
    """
    if password and PIKEPDF_OK:
        try:
            buf = io.BytesIO()
            with pikepdf.Pdf.open(filepath, password=password) as pdf:
                pdf.save(buf)
            buf.seek(0)
            return pdfplumber.open(buf)
        except Exception:
            pass
    return pdfplumber.open(filepath)


def extract_text_all_pages(filepath: str, password: str = '', max_pages: int = 20) -> list[str]:
    """
    Extract text from each page using pdfplumber.
    Returns list of strings, one per page.
    """
    if not PDFPLUMBER_OK:
        return []
    pages_text = []
    try:
        with open_pdf(filepath, password) as pdf:
            for i, page in enumerate(pdf.pages[:max_pages]):
                text = page.extract_text() or ''
                pages_text.append(text)
    except Exception as e:
        pages_text.append('')
    return pages_text


def is_vectorized_pdf(filepath: str, password: str = '', sample_pages: int = 2) -> bool:
    """
    Returns True if the FIRST page (transactions page) uses vectorized text.
    Checks only the first 1-2 pages — later pages often have regular terms/MITC text.
    """
    if not PDFPLUMBER_OK:
        return True
    try:
        with open_pdf(filepath, password) as pdf:
            # Check first page specifically — transactions are always on page 1
            page1_text = (pdf.pages[0].extract_text() or '').strip()
            if len(page1_text) < 50:
                return True
            # Also check if page 1 has ANY date-like pattern (DD/MM/YYYY)
            import re
            if not re.search(r'\d{2}/\d{2}/\d{4}', page1_text) and len(page1_text) < 200:
                return True
            return False
    except Exception:
        return True


def ocr_pages(filepath: str, password: str = '', pages: list[int] = None,
              dpi: int = 300) -> list[str]:
    """
    OCR specified pages (1-indexed). Returns list of OCR text strings.
    Falls back to pdfplumber text if OCR not available.
    """
    if not PDF2IMAGE_OK or not TESSERACT_OK:
        # Fallback: try pdfplumber
        all_pages = extract_text_all_pages(filepath, password)
        if pages:
            return [all_pages[p-1] for p in pages if p-1 < len(all_pages)]
        return all_pages

    results = []
    try:
        if password and PIKEPDF_OK:
            buf = io.BytesIO()
            with pikepdf.Pdf.open(filepath, password=password) as pdf:
                pdf.save(buf)
            buf.seek(0)
            img_source = {'pdf_file': buf}
        else:
            img_source = {'pdf_path': filepath}

        if pages:
            first, last = min(pages), max(pages)
        else:
            first, last = 1, 5  # default: first 5 pages

        if 'pdf_file' in img_source:
            images = convert_from_bytes(img_source['pdf_file'].read(),
                                        dpi=dpi, first_page=first, last_page=last)
        else:
            images = convert_from_path(img_source['pdf_path'],
                                       dpi=dpi, first_page=first, last_page=last)

        for img in images:
            text = pytesseract.image_to_string(img, config='--psm 6')
            results.append(text)
    except Exception as e:
        results.append('')
    return results


def get_page_count(filepath: str, password: str = '') -> int:
    """Return total page count of PDF."""
    if not PDFPLUMBER_OK:
        return 0
    try:
        with open_pdf(filepath, password) as pdf:
            return len(pdf.pages)
    except Exception:
        return 0
