#!/usr/bin/env python3
"""
Foto2AP Service — OCR-based AP recognition from photos.

Extracts and refines the core logic from Foto2AP/INSERT_NAME/foto2ap.ipynb
into a reusable service module.

Usage (standalone):
    python foto2ap_service.py /path/to/image.jpg

Usage (import):
    from foto2ap_service import recognize_ap
    result = recognize_ap(image_bytes)
"""

import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

import numpy as np
from rapidfuzz import process, fuzz

# ---------------------------------------------------------------------------
# Faculties & OCR confusion map (from the notebook)
# ---------------------------------------------------------------------------
FACULTIES = [
    'DRET', 'CIEN', 'AMICS', 'LLET', 'ETSE', 'MED', 'CEDU', 'IGOP', 'EUREKA',
    'BIBCIE', 'BIBSOC', 'BIBHUM', 'CIVIC', 'CCOM', 'REC', 'MRC', 'DISP', 'B13',
    'SAF', 'AULAJ', 'HEMER', 'VET', 'GTIP', 'VH', 'ECON', 'QUIM', 'CREA', 'FTI',
    'POL', 'EDBLANC', 'ESCDOC', 'ECOSOC', 'IUEE', 'TERMICA', 'IBB', 'CBATEG',
    'SI', 'IDIOMES', 'TAULI', 'SAB', 'DEMOGRAF', 'DEIXALLERIA', 'MRB', 'EST',
    'SPAU', 'ICTAIC', 'MRA',
]

OCR_CONFUSIONS = {
    '0': ['O'], 'O': ['0'],
    '1': ['I', 'L'], 'I': ['1'], 'L': ['1'],
    '5': ['S'], 'S': ['5'],
    '3': ['E'], 'E': ['3'],
    '7': ['T'], 'T': ['7'],
    '8': ['B'], 'B': ['8'],
    '6': ['G'], 'G': ['6'],
    '2': ['Z'], 'Z': ['2'],
    'A': ['4'], '4': ['A'],
    'P': ['F'], 'F': ['P'],
}

FUZZY_THRESHOLD = 80
SUBSTITUTION_THRESHOLD = 75

# Regex helpers
_PREFIX_RE = re.compile(r'^[A4R]?[PF]?[-_.\\s]?([A-Z0-9]{2,})$')
_TRAILING_DIGITS_RE = re.compile(r'^(.*?)(\d+)$')

# ---------------------------------------------------------------------------
# GeoJSON data (lazy-loaded)
# ---------------------------------------------------------------------------
_GEOJSON_DATA: Optional[dict] = None
_GEOJSON_PATH = Path(__file__).resolve().parent / "geolocation_package" / "data" / "aps_geolocalizados_wgs84.geojson"


def _load_geojson() -> dict:
    global _GEOJSON_DATA
    if _GEOJSON_DATA is None:
        if not _GEOJSON_PATH.exists():
            raise FileNotFoundError(f"GeoJSON not found: {_GEOJSON_PATH}")
        with open(_GEOJSON_PATH) as f:
            _GEOJSON_DATA = json.load(f)
    return _GEOJSON_DATA


def _find_ap_in_geojson(ap_name: str) -> Optional[dict]:
    """Look up an AP name in the GeoJSON and return its properties + coords."""
    geojson = _load_geojson()
    target = ap_name.strip().upper()
    for feature in geojson["features"]:
        props = feature["properties"]
        name = (props.get("USER_NOM_A") or "").strip().upper()
        if name == target:
            coords = feature["geometry"]["coordinates"]
            return {
                "ap_name": props.get("USER_NOM_A"),
                "lat": float(coords[1]),
                "lng": float(coords[0]),
                "building": props.get("USER_EDIFI", "Unknown"),
                "floor": int(props.get("Num_Planta", 0) or 0),
                "espacio": props.get("USER_Espai", ""),
            }
    return None


# ---------------------------------------------------------------------------
# OCR text normalisation & AP code parsing (from the notebook)
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Uppercase and strip punctuation/spaces likely introduced by OCR."""
    text = text.upper()
    for ch in ' _.,;:|\\\\/-\\t':
        text = text.replace(ch, '')
    return text


def ocr_variants(token: str):
    """Generate candidate strings by substituting one OCR-confused character at a time."""
    for i, ch in enumerate(token):
        if ch in OCR_CONFUSIONS:
            for replacement in OCR_CONFUSIONS[ch]:
                yield token[:i] + replacement + token[i+1:]


def best_faculty_match(candidate: str) -> Optional[str]:
    """Try to match candidate to a known faculty code (direct + OCR-corrected)."""
    # Direct fuzzy match
    result = process.extractOne(candidate, FACULTIES, scorer=fuzz.WRatio)
    if result and result[1] >= FUZZY_THRESHOLD:
        return result[0]

    # Try single-character OCR substitutions
    best_score = 0
    best_faculty = None
    for variant in ocr_variants(candidate):
        result = process.extractOne(variant, FACULTIES, scorer=fuzz.WRatio)
        if result and result[1] > best_score:
            best_score = result[1]
            best_faculty = result[0]

    if best_score >= SUBSTITUTION_THRESHOLD:
        return best_faculty

    return None


def _strip_ap_prefix(text: str) -> Optional[str]:
    """Strip AP prefix and separator, return payload or None."""
    if 'A' not in text and '4' not in text:
        return None

    m = _PREFIX_RE.match(text)
    if m:
        return m.group(1)

    # Fallback: take everything after first '-'
    if '-' in text:
        payload = text.split('-', 1)[1]
        if len(payload) >= 2:
            return payload

    return None


def parse_ap_code(ocr_text: str) -> Optional[str]:
    """Parse a single OCR string into canonical AP-{FACULTY}{number}."""
    text = normalize(ocr_text)

    payload = _strip_ap_prefix(text)
    if payload is None:
        return None

    # Split payload into faculty candidate + trailing number
    m = _TRAILING_DIGITS_RE.match(payload)
    if m:
        fac_candidate = m.group(1)
        number = m.group(2)
    else:
        fac_candidate = payload
        number = ''

    if not fac_candidate:
        return None

    faculty = best_faculty_match(fac_candidate)
    if faculty is None:
        return None

    if not number:
        return None

    return f'AP-{faculty}{number}'


def extract_best_ap_code_from_texts(texts: list[str]) -> Optional[str]:
    """Convenience: flat list of OCR strings → best AP code or None."""
    candidates = [parse_ap_code(t) for t in texts]
    candidates = [c for c in candidates if c is not None]
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# PaddleOCR integration (lazy-loaded)
# ---------------------------------------------------------------------------
_OCR = None


def _get_ocr():
    global _OCR
    if _OCR is None:
        try:
            from paddleocr import PaddleOCR
            _OCR = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
        except ImportError:
            raise ImportError(
                "PaddleOCR is required. Install with: "
                "pip install paddleocr paddlepaddle"
            )
    return _OCR


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recognize_ap(image_bytes: bytes) -> Optional[dict]:
    """
    Recognise an AP from a photo (raw bytes).

    Args:
        image_bytes: Raw JPEG/PNG image bytes.

    Returns:
        dict with keys {ap_name, lat, lng, building, floor, espacio}
        or None if no AP could be recognised.
    """
    # 1. Load image
    try:
        import cv2
        import numpy as np
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return None
    except Exception:
        return None

    # 2. OCR
    ocr = _get_ocr()
    try:
        result = ocr.ocr(img)
    except Exception:
        return None

    if not result or not result[0]:
        return None

    # 3. Extract texts from PaddleOCR output
    # PaddleOCR returns: [ [ [[x1,y1],...], (text, score) ], ... ]
    # result[0] is a list of per-detection results, each being:
    #   [ [bbox_coords], (text, score) ]
    rec_texts = []
    raw_detections = result[0] if isinstance(result[0], list) else []
    for det in raw_detections:
        if isinstance(det, (list, tuple)) and len(det) >= 2:
            text_score = det[1]
            if isinstance(text_score, (list, tuple)) and len(text_score) >= 1:
                rec_texts.append(str(text_score[0]))
    if not rec_texts:
        # Fallback: try dict format (some PaddleOCR versions)
        try:
            rec_texts = result[0].get("rec_texts", [])
        except AttributeError:
            pass
    if not rec_texts:
        # Last resort: try flat list of strings
        for det in raw_detections:
            if isinstance(det, str):
                rec_texts.append(det)

    if not rec_texts:
        return None

    # 4. Parse AP code
    ap_code = extract_best_ap_code_from_texts(rec_texts)
    if ap_code is None:
        return None

    # 5. Look up coordinates in GeoJSON
    ap_info = _find_ap_in_geojson(ap_code)
    return ap_info


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python foto2ap_service.py <image_path>")
        sys.exit(1)

    path = sys.argv[1]
    with open(path, "rb") as f:
        img_bytes = f.read()

    result = recognize_ap(img_bytes)
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("No AP recognised.")
        sys.exit(1)
