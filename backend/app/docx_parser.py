"""Parse a .docx exam file into structured exam data.

The parser detects:
  - Multiple-choice questions ("Câu N: ... A. ... B. ... C. ... D. ...")
    with the correct answer marked by RED text color (FF0000) on the option
    letter or option content.
  - True/False questions (Phần II) with 4 sub-statements a/b/c/d. The
    correct answers are read from a small table that follows each TF
    question (rows like "a) Đúng", "b) Sai", ...).
  - Embedded images inside questions/options. They are saved to disk and
    referenced inline using a `[IMG:<url>]` marker.
  - Math formulas (OMML, <m:oMath>) — the inner text is linearised and
    inlined as `[MATH:<text>]` so teachers can edit them later.

The output schema matches what the rest of the backend expects:
{
    "title": str,
    "sections": [
        {"title": "PHẦN I ...", "questions": [
            {"question": "...", "options": {"A": "..", ...},
             "answer": "A"|"B"|"C"|"D"|None,
             "images": [url, ...]}
        ]}
    ],
    "tf_questions": [
        {"question": "...", "statements": {"a": "..", ...},
         "answers": {"a": True/False, ...}, "images": [url, ...]}
    ],
    "warnings": [str, ...],
}
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from docx.oxml.ns import qn

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

R_OPEN = "[[R]]"
R_CLOSE = "[[/R]]"


def _qn(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _is_red(rpr) -> bool:
    if rpr is None:
        return False
    cl = rpr.find(qn("w:color"))
    return cl is not None and (cl.get(qn("w:val")) or "").upper() == "FF0000"


def _omath_text(omath) -> str:
    """Linearise an OMML element to a readable string."""
    parts = []
    for t in omath.iter(_qn(M_NS, "t")):
        parts.append(t.text or "")
    text = "".join(parts).strip()
    return text


def _save_image(part, image_dir: str, url_prefix: str) -> Optional[str]:
    """Persist an image part to disk; return its public URL."""
    blob = getattr(part, "blob", None)
    if blob is None:
        return None
    ext = ".png"
    name = getattr(part, "partname", "")
    if name:
        ext_guess = os.path.splitext(str(name))[1]
        if ext_guess:
            ext = ext_guess
    digest = hashlib.sha1(blob).hexdigest()[:16]
    filename = f"{digest}{ext}"
    os.makedirs(image_dir, exist_ok=True)
    fpath = os.path.join(image_dir, filename)
    if not os.path.exists(fpath):
        with open(fpath, "wb") as f:
            f.write(blob)
    return f"{url_prefix.rstrip('/')}/{filename}"


def _walk_paragraph(p, doc_part, image_dir: str, url_prefix: str) -> Tuple[str, List[str]]:
    """Walk paragraph elements in document order; return (text_with_red_markers, images)."""
    out: List[str] = []
    images: List[str] = []

    def visit(node):
        tag = node.tag
        if tag == _qn(W_NS, "r"):
            rpr = node.find(qn("w:rPr"))
            red = _is_red(rpr)
            # Walk children in order
            for child in node:
                ctag = child.tag
                if ctag == _qn(W_NS, "t"):
                    text = child.text or ""
                    if text:
                        if red:
                            out.append(R_OPEN + text + R_CLOSE)
                        else:
                            out.append(text)
                elif ctag == _qn(W_NS, "tab"):
                    out.append("\t")
                elif ctag == _qn(W_NS, "br"):
                    out.append("\n")
                elif ctag == _qn(W_NS, "drawing") or ctag == _qn(W_NS, "pict"):
                    # Find blip with r:embed
                    for blip in child.iter(_qn(A_NS, "blip")):
                        rid = blip.get(_qn(R_NS, "embed"))
                        if rid and rid in doc_part.related_parts:
                            url = _save_image(doc_part.related_parts[rid], image_dir, url_prefix)
                            if url:
                                images.append(url)
                                out.append(f"[IMG:{url}]")
                                break
                elif ctag == _qn(M_NS, "oMath") or ctag == _qn(M_NS, "oMathPara"):
                    text = _omath_text(child)
                    if text:
                        out.append(f"[MATH:{text}]")
                else:
                    # Drill into other run children that may contain math/drawings
                    for sub in child.iter():
                        if sub.tag == _qn(M_NS, "oMath"):
                            text = _omath_text(sub)
                            if text:
                                out.append(f"[MATH:{text}]")
                            break
        elif tag == _qn(M_NS, "oMath") or tag == _qn(M_NS, "oMathPara"):
            text = _omath_text(node)
            if text:
                out.append(f"[MATH:{text}]")
        else:
            for child in node:
                visit(child)

    for child in p:
        visit(child)

    s = "".join(out)
    while "[[/R]][[R]]" in s:
        s = s.replace("[[/R]][[R]]", "")
    return s, images


def _table_answers(tbl) -> Dict[str, bool]:
    """Read TF answer table → {a: True, b: False, ...}."""
    results: Dict[str, bool] = {}
    for row in tbl.iter(qn("w:tr")):
        for cell in row.iter(qn("w:tc")):
            txt = ""
            for p in cell.iter(qn("w:p")):
                for t in p.iter(qn("w:t")):
                    txt += t.text or ""
            txt = txt.strip()
            m = re.match(r"([a-dA-D])\)?\s*(Đúng|Sai)", txt, re.IGNORECASE)
            if m:
                letter = m.group(1).lower()
                val = m.group(2)
                results[letter] = val.lower().startswith("đ")
    return results


def _strip_red(s: str) -> str:
    return s.replace(R_OPEN, "").replace(R_CLOSE, "")


def _starts_with_cau(p: str) -> bool:
    """Return True if paragraph starts with a question marker (Câu N), tolerating
    leading markers like [IMG:...] or [MATH:...] from inline content."""
    s = _strip_red(p).strip()
    s = re.sub(r"^(?:\[(?:IMG|MATH):[^\]]*\]\s*)+", "", s)
    return bool(re.match(r"^\s*C[âa]u\s*\d+\b", s))


def _strip_cau_prefix(text: str) -> str:
    """Strip a leading 'Câu N.' marker, even when preceded by inline IMG/MATH markers."""
    leading = ""
    rest = text
    m_lead = re.match(r"^((?:\[(?:IMG|MATH):[^\]]*\]\s*)*)", rest)
    if m_lead:
        leading = m_lead.group(1)
        rest = rest[m_lead.end():]
    m = re.match(r"^\s*C[âa]u\s*\d+\s*[:.\-]?\s*", rest)
    if m:
        rest = rest[m.end():].strip()
    return (leading + rest).strip()


def _red_spans(s: str) -> Tuple[str, List[Tuple[int, int]]]:
    """Return (clean_text, list_of_red_spans_in_clean_text)."""
    out: List[str] = []
    spans: List[Tuple[int, int]] = []
    i = 0
    red_start = 0
    in_red = False
    while i < len(s):
        if s[i:i + len(R_OPEN)] == R_OPEN:
            in_red = True
            red_start = sum(len(x) for x in out)
            i += len(R_OPEN)
        elif s[i:i + len(R_CLOSE)] == R_CLOSE:
            in_red = False
            spans.append((red_start, sum(len(x) for x in out)))
            i += len(R_CLOSE)
        else:
            out.append(s[i])
            i += 1
    return "".join(out), spans


def _parse_mc(block_text: str) -> Optional[Dict[str, Any]]:
    clean, spans = _red_spans(block_text)
    matches: List[Tuple[int, str, int]] = []
    # Allow option markers to follow whitespace, newline, or any non-alphanumeric
    # character (e.g. '?A.' or ']A.' from inline images).
    for m in re.finditer(r"(?:^|(?<=[^A-Za-zÀ-ỹ0-9]))([A-D])\s*[.)]", clean):
        matches.append((m.start(1), m.group(1), m.end()))
    expected = ["A", "B", "C", "D"]
    picked: List[Tuple[int, str, int]] = []
    idx = 0
    last_end = -1
    for pos, letter, end in matches:
        if idx < 4 and letter == expected[idx] and end > last_end:
            picked.append((pos, letter, end))
            last_end = end
            idx += 1
    if len(picked) < 4:
        picked = []
        for want in expected:
            for pos, letter, end in matches:
                if letter == want:
                    picked.append((pos, letter, end))
                    break
        if len(picked) < 4:
            return None
    q_end = picked[0][0]
    question_text = _strip_cau_prefix(clean[:q_end].strip())
    options: Dict[str, str] = {}
    for i, (pos, letter, end) in enumerate(picked):
        opt_end = picked[i + 1][0] if i + 1 < len(picked) else len(clean)
        options[letter] = clean[end:opt_end].strip()
    red_coverage = {letter: 0 for letter in expected}
    for i, (pos, letter, end) in enumerate(picked):
        opt_end = picked[i + 1][0] if i + 1 < len(picked) else len(clean)
        for s, e in spans:
            ov_start = max(s, pos)
            ov_end = min(e, opt_end)
            if ov_end > ov_start:
                red_coverage[letter] += ov_end - ov_start
    answer_letter, max_cov = max(red_coverage.items(), key=lambda x: x[1])
    return {
        "question": question_text,
        "options": options,
        "answer": answer_letter if max_cov > 0 else None,
    }


def _parse_short_answer(block_text: str) -> Optional[Dict[str, Any]]:
    """Parse a 'short answer' question. Format:
    "Câu N. <body...> Đáp án: <answer>"
    Returns {"question": str, "answer": str}.
    """
    clean = _strip_red(block_text).strip()
    if not clean:
        return None
    m = re.search(r"Đ[áa]p\s*[áa]n\s*[:\-]\s*([^\n]+)", clean, re.IGNORECASE)
    if not m:
        # No answer marker — keep question, mark unknown answer
        text = _strip_cau_prefix(clean)
        return {"question": text, "answer": None}
    answer = m.group(1).strip().rstrip(".")
    body = clean[: m.start()].strip()
    body = _strip_cau_prefix(body)
    return {"question": body, "answer": answer}


def _parse_tf(block_text: str, tbl_answers: Dict[str, bool]) -> Optional[Dict[str, Any]]:
    clean, _ = _red_spans(block_text)
    expected = ["a", "b", "c", "d"]
    # First pass: try strict a/b/c/d sequence
    picked: List[Tuple[int, str, int]] = []
    idx = 0
    last_end = -1
    for m in re.finditer(r"(?:^|(?<=[^A-Za-zÀ-ỹ0-9]))([a-d])\s*[.)]", clean):
        letter = m.group(1)
        if idx < 4 and letter == expected[idx] and m.end() > last_end:
            picked.append((m.start(1), letter, m.end()))
            last_end = m.end()
            idx += 1
    # Fallback: if strict sequence failed (e.g. docx typo a)/b)/c)/c)), take the
    # first 4 statement-style markers in order and map to a/b/c/d.
    if len(picked) < 4:
        all_matches = list(re.finditer(r"(?:^|(?<=[^A-Za-zÀ-ỹ0-9]))([a-d])\s*[.)]", clean))
        if len(all_matches) >= 4:
            picked = []
            for k, m in enumerate(all_matches[:4]):
                picked.append((m.start(1), expected[k], m.end()))
        else:
            return None
    q_end = picked[0][0]
    question_text = _strip_cau_prefix(clean[:q_end].strip())
    statements: Dict[str, str] = {}
    for i, (pos, letter, end) in enumerate(picked):
        stmt_end = picked[i + 1][0] if i + 1 < len(picked) else len(clean)
        statements[letter] = clean[end:stmt_end].strip()
    return {
        "question": question_text,
        "statements": statements,
        "answers": tbl_answers,
    }


def parse_docx(path: str, image_dir: str, url_prefix: str) -> Dict[str, Any]:
    """Main entry point — parse the docx file and return structured exam."""
    warnings: List[str] = []
    doc = Document(path)
    body = doc.element.body
    items: List[Tuple[str, Any, List[str]]] = []  # (kind, value, images)
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            txt, imgs = _walk_paragraph(child, doc.part, image_dir, url_prefix)
            if txt.strip() or imgs:
                items.append(("p", txt, imgs))
        elif tag == "tbl":
            # First, collect any images in the table
            table_imgs: List[str] = []
            for blip in child.iter(_qn(A_NS, "blip")):
                rid = blip.get(_qn(R_NS, "embed"))
                if rid and rid in doc.part.related_parts:
                    url = _save_image(doc.part.related_parts[rid], image_dir, url_prefix)
                    if url:
                        table_imgs.append(url)
            answers = _table_answers(child)
            items.append(("tbl", answers, table_imgs))

    # Locate True/False section header and Short-answer section header.
    # Match both Roman numerals (Phần II) and Vietnamese numbers (Phần 2.) variations,
    # case-insensitive on the "Phần"/"PHẦN" prefix.
    tf_start: Optional[int] = None
    sa_start: Optional[int] = None
    tf_pat = re.compile(r"ph[ầa]n\s+(?:ii\b|2\b)", re.IGNORECASE)
    sa_pat = re.compile(r"ph[ầa]n\s+(?:iii\b|3\b)", re.IGNORECASE)
    for i, (t, v, _imgs) in enumerate(items):
        if t != "p" or not isinstance(v, str):
            continue
        s = _strip_red(v)
        sl = s.lower()
        if tf_start is None and tf_pat.search(sl) and "đúng sai" in sl:
            tf_start = i
        elif sa_start is None and (
            (sa_pat.search(sl) and ("trả lời ngắn" in sl or "tra loi ngan" in sl))
            or "trả lời ngắn" in sl
        ):
            sa_start = i

    # Slice items into 3 sections in document order.
    mc_end = tf_start if tf_start is not None else (sa_start if sa_start is not None else len(items))
    tf_end = sa_start if sa_start is not None else len(items)
    mc_items = items[:mc_end]
    tf_items = items[tf_start + 1: tf_end] if tf_start is not None else []
    sa_items = items[sa_start + 1:] if sa_start is not None else []

    # Sub-sections within MC (e.g. "Phần 1. Trắc nghiệm nhiều lựa chọn" header is included).
    sections: List[Dict[str, Any]] = []
    current_section: Dict[str, Any] = {"title": "PHẦN I", "items": []}
    sec_pat = re.compile(r"^\s*ph[ầa]n\s+(?:[ivx]+|\d+)\b[.:]?", re.IGNORECASE)
    for t, v, imgs in mc_items:
        if t == "p" and isinstance(v, str) and sec_pat.match(_strip_red(v).strip()):
            if current_section["items"]:
                sections.append(current_section)
            current_section = {"title": _strip_red(v).strip(), "items": []}
        else:
            current_section["items"].append((t, v, imgs))
    if current_section["items"]:
        sections.append(current_section)

    out_sections: List[Dict[str, Any]] = []
    for section in sections:
        # Split by "Câu N"
        questions: List[List[Tuple[str, Any, List[str]]]] = []
        current: List[Tuple[str, Any, List[str]]] = []
        for t, v, imgs in section["items"]:
            if t == "p" and isinstance(v, str) and _starts_with_cau(v):
                if current:
                    questions.append(current)
                current = [(t, v, imgs)]
            else:
                current.append((t, v, imgs))
        if current:
            questions.append(current)
        section_qs: List[Dict[str, Any]] = []
        for q_blocks in questions:
            texts = [v for t, v, _ in q_blocks if t == "p"]
            imgs: List[str] = []
            for t, _v, im in q_blocks:
                imgs.extend(im)
            if not texts:
                continue
            block = "\n".join(texts)
            parsed = _parse_mc(block)
            if parsed:
                parsed["images"] = imgs
                if parsed.get("answer") is None:
                    warnings.append(f"Không tìm thấy đáp án (đỏ) cho: {parsed['question'][:60]}…")
                section_qs.append(parsed)
        if section_qs:
            out_sections.append({"title": section["title"], "questions": section_qs})

    # TF
    tf_qs: List[Dict[str, Any]] = []
    current_tf: List[Tuple[str, Any, List[str]]] = []
    grouped: List[List[Tuple[str, Any, List[str]]]] = []
    for t, v, imgs in tf_items:
        if t == "p" and isinstance(v, str) and _starts_with_cau(v):
            if current_tf:
                grouped.append(current_tf)
            current_tf = [(t, v, imgs)]
        else:
            current_tf.append((t, v, imgs))
    if current_tf:
        grouped.append(current_tf)
    for g in grouped:
        texts = [v for t, v, _ in g if t == "p"]
        tables = [v for t, v, _ in g if t == "tbl"]
        imgs: List[str] = []
        for t, _v, im in g:
            imgs.extend(im)
        if not texts:
            continue
        if not tables:
            warnings.append("Câu Đúng/Sai thiếu bảng đáp án — bỏ qua.")
            continue
        block = "\n".join(texts)
        parsed = _parse_tf(block, tables[0])
        if parsed:
            parsed["images"] = imgs
            tf_qs.append(parsed)

    # Short-answer questions
    sa_qs: List[Dict[str, Any]] = []
    sa_groups: List[List[Tuple[str, Any, List[str]]]] = []
    sa_current: List[Tuple[str, Any, List[str]]] = []
    for t, v, imgs in sa_items:
        if t == "p" and isinstance(v, str) and _starts_with_cau(v):
            if sa_current:
                sa_groups.append(sa_current)
            sa_current = [(t, v, imgs)]
        else:
            sa_current.append((t, v, imgs))
    if sa_current:
        sa_groups.append(sa_current)
    for g in sa_groups:
        texts = [v for t, v, _ in g if t == "p"]
        imgs: List[str] = []
        for t, _v, im in g:
            imgs.extend(im)
        if not texts:
            continue
        block = "\n".join(texts)
        parsed = _parse_short_answer(block)
        if parsed:
            parsed["images"] = imgs
            if parsed.get("answer") is None:
                warnings.append(f"Không tìm thấy đáp án cho câu trả lời ngắn: {parsed['question'][:60]}…")
            sa_qs.append(parsed)

    return {
        "sections": out_sections,
        "tf_questions": tf_qs,
        "short_answer_questions": sa_qs,
        "warnings": warnings,
    }
