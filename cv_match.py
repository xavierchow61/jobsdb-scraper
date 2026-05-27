"""CV-based job matching: extract CV keywords/years from PDF; score each JD.

Public API:
    load_cv(path) -> CVProfile or None on failure
    score_job(profile, job_row) -> (score_int_0_100, list_of_matched_keywords)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

try:
    from pdfminer.high_level import extract_text as _pdf_extract_text
except ImportError:
    _pdf_extract_text = None


# ----- sentence-transformers lazy loader -----
_st_model = None
_st_init_error = None


def _get_model():
    """Lazy-load the sentence-transformer model. Returns None if unavailable."""
    global _st_model, _st_init_error
    if _st_model is not None:
        return _st_model
    if _st_init_error is not None:
        return None
    try:
        from sentence_transformers import SentenceTransformer
        print("  [semantic] loading model 'all-MiniLM-L6-v2' "
              "(first run downloads ~80MB)...")
        _st_model = SentenceTransformer("all-MiniLM-L6-v2")
        print("  [semantic] model ready.")
    except Exception as e:
        _st_init_error = e
        print(f"  [semantic] disabled (load failed): {e}")
        return None
    return _st_model


def _cosine(a, b):
    import numpy as np
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def compute_semantic_score(cv_embedding, job_text):
    """Cosine similarity between cv_embedding and job_text embedding.

    Returns an int 0-100 (rescaled from raw cosine 0.2-0.8 range),
    or None if the model is unavailable or job_text is too thin.
    """
    if not job_text or len(job_text.strip()) < 80:
        return None
    model = _get_model()
    if model is None:
        return None
    job_emb = model.encode(job_text, convert_to_numpy=True,
                           show_progress_bar=False)
    sim = _cosine(cv_embedding, job_emb)
    # Raw cosine for HR text usually lives in 0.15-0.75. Stretch to 0-100.
    score = round((sim - 0.15) / 0.60 * 100)
    return max(0, min(100, score))


def cv_embedding(cv_text):
    """Compute CV embedding once. Returns None if model unavailable."""
    if not cv_text:
        return None
    model = _get_model()
    if model is None:
        return None
    return model.encode(cv_text, convert_to_numpy=True,
                        show_progress_bar=False)


# Curated HK accounting/finance vocabulary. Each entry is a keyword phrase
# we look for (case-insensitive substring match). Order does not matter.
VOCAB = [
    # Certifications
    "cfa", "acca", "cpa", "hkicpa", "aicpa", "frm", "cisa", "cma", "fcca",
    "chartered accountant", "chartered financial analyst",
    # Standards & frameworks
    "ifrs", "hkfrs", "us gaap", "sox", "ifrs 9", "ifrs 15", "ifrs 16",
    "hkas", "hk gaap", "ind as", "basel",
    # Software / ERP
    "sap", "oracle", "netsuite", "quickbooks", "myob", "xero", "sage",
    "great plains", "peachtree", "dynamics", "workday", "hyperion",
    "essbase", "concur", "blackline",
    # Excel / data tools
    "excel", "vlookup", "pivot table", "power bi", "powerbi", "tableau",
    "vba", "macro", "alteryx", "python", "sql",
    # Accounting domain
    "accounts payable", "accounts receivable", "general ledger",
    "consolidation", "full set", "month end", "year end",
    "full set of accounts", "audit", "internal control", "reconciliation",
    "fixed assets", "inventory", "cost accounting", "fp&a", "fpa",
    "treasury", "cash flow", "forecasting", "budgeting", "variance",
    "intercompany", "credit control", "credit analysis", "compliance",
    "kyc", "aml", "transfer pricing", "due diligence",
    "tax planning", "tax compliance", "tax filing",
    # Industries
    "manufacturing", "trading", "retail", "fintech", "banking", "insurance",
    "construction", "logistics", "real estate", "hospitality", "shipping",
    "asset management", "investment banking", "private equity", "hedge fund",
    "listed company", "mnc", "multinational",
    # Languages
    "cantonese", "mandarin", "putonghua",
    # Big 4
    "big 4", "big four", "kpmg", "ernst & young", "ernst and young",
    "pwc", "pricewaterhousecoopers", "deloitte",
    # Leadership
    "leadership", "team management", "supervisor", "manager",
    # Chinese accounting terms
    "會計", "審計", "稅務", "財務報表", "全盤", "月結", "年結", "對賬",
    "預算", "管理層報表", "上市公司", "內部控制", "成本會計", "應收",
    "應付", "總帳", "合併報表",
]

# We dedupe and lowercase the vocab once at import time.
_VOCAB_LOWER = list(dict.fromkeys(v.strip().lower() for v in VOCAB if v.strip()))


YEAR_PAT = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:to\s*\d{1,2}\s*)?(?:years?|yrs?)\b",
    re.IGNORECASE,
)


@dataclass
class CVProfile:
    keywords: set
    years: int | None
    raw_chars: int
    # Optional source path so we know where to save edits.
    source_path: str = ""
    # Full extracted CV text (for semantic embedding). Not persisted to JSON.
    cv_text: str = ""

    def summary(self) -> str:
        return (
            f"CV loaded: {len(self.keywords)} matched keywords, "
            f"{self.years or '?'} years experience, "
            f"{self.raw_chars} chars text"
        )

    def to_dict(self) -> dict:
        return {
            "keywords": sorted(self.keywords),
            "years": self.years,
            "raw_chars": self.raw_chars,
            "source_path": self.source_path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CVProfile":
        return cls(
            keywords=set(d.get("keywords") or []),
            years=d.get("years"),
            raw_chars=int(d.get("raw_chars") or 0),
            source_path=d.get("source_path", ""),
        )


def profile_json_path(cv_path: str | Path) -> Path:
    """Where do we save edits for this CV? Sibling .profile.json."""
    p = Path(cv_path)
    return p.with_suffix(p.suffix + ".profile.json")


def save_profile(profile: CVProfile, json_path: str | Path | None = None) -> Path:
    """Persist the user's edited keywords to disk."""
    if json_path is None:
        if not profile.source_path:
            raise ValueError("No source_path on profile; pass json_path explicitly.")
        json_path = profile_json_path(profile.source_path)
    p = Path(json_path)
    p.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p


def load_profile_json(json_path: str | Path) -> CVProfile | None:
    p = Path(json_path)
    if not p.exists():
        return None
    try:
        return CVProfile.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception as e:
        print(f"  [CV] failed to read profile {p}: {e}")
        return None


def extract_text(path: str | Path) -> str:
    """Read a CV file (PDF / TXT / DOCX-not-supported) and return plain text."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    suf = p.suffix.lower()
    if suf == ".pdf":
        if _pdf_extract_text is None:
            raise RuntimeError(
                "pdfminer.six not installed; cannot read PDF CV. "
                "Run: pip install pdfminer.six"
            )
        return _pdf_extract_text(str(p)) or ""
    if suf in (".txt", ".md", ""):
        return p.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"Unsupported CV file type: {suf!r}. Use .pdf or .txt.")


def extract_keywords(text: str, vocab: Iterable[str] = _VOCAB_LOWER) -> set:
    if not text:
        return set()
    lower = " " + text.lower() + " "
    found = set()
    for kw in vocab:
        # Word-boundary-ish for short keywords (cfa, acca) to avoid false hits
        if len(kw) <= 5 and kw.isalpha():
            if re.search(rf"\b{re.escape(kw)}\b", lower):
                found.add(kw)
        else:
            if kw in lower:
                found.add(kw)
    return found


def extract_max_years(text: str) -> int | None:
    if not text:
        return None
    nums = [int(m.group(1)) for m in YEAR_PAT.finditer(text)]
    return max(nums) if nums else None


def dedupe_substrings(kw_set: set) -> set:
    """If both 'full set' and 'full set of accounts' match, keep only the
    longer (more specific) one. Prevents double-counting the same JD phrase.
    """
    sorted_by_len = sorted(kw_set, key=lambda k: (-len(k), k))
    kept = []
    for kw in sorted_by_len:
        if not any(kw != bigger and kw in bigger for bigger in kept):
            kept.append(kw)
    return set(kept)


def load_cv(path: str | Path, use_saved_profile: bool = True) -> CVProfile | None:
    """Load a CV file and return a CVProfile.

    Always reads the PDF text (needed for semantic embedding). If a
    sibling .profile.json exists, its edited keywords + years override the
    auto-extracted ones.
    Returns None on failure.
    """
    p = Path(path)
    try:
        text = extract_text(p)
    except Exception as e:
        print(f"  [CV] failed to read {p}: {e}")
        return None

    if use_saved_profile:
        saved = load_profile_json(profile_json_path(p))
        if saved is not None:
            saved.source_path = str(p)
            saved.cv_text = text
            saved.raw_chars = len(text)
            return saved

    keywords = extract_keywords(text)
    years = extract_max_years(text)
    return CVProfile(
        keywords=keywords, years=years, raw_chars=len(text),
        source_path=str(p), cv_text=text,
    )


def _score_keyword(profile, job_row, haystack):
    """Original keyword-based score (used as fallback for thin JDs)."""
    search_vocab = set(_VOCAB_LOWER) | {k.lower() for k in profile.keywords}
    job_kw = dedupe_substrings(extract_keywords(haystack, search_vocab))
    cv_kw_lc = {k.lower() for k in profile.keywords}
    matched = job_kw & cv_kw_lc
    if not job_kw:
        return 0, []
    coverage = len(matched) / max(len(job_kw), 3)
    abundance = min(len(matched), 6) / 6
    score = round(100 * (coverage * 0.5 + abundance * 0.5))
    return score, sorted(matched)


def score_job(profile: CVProfile, job_row: dict) -> tuple[int, list]:
    """Return (score, matched_keyword_list).

    Semantic-first, keyword-fallback:
      * If JD has substantive Responsibilities + Requirements text (>=80 chars)
        AND CV text + embedding model available → use cosine similarity score.
      * Otherwise → fall back to keyword coverage/abundance score.
    Apply +/- years adjustment in either path.
    """
    if profile is None:
        return 0, []

    haystack = " ".join(
        str(job_row.get(k, "") or "")
        for k in (
            "Job Title", "Classification", "Responsibilities",
            "Requirements", "Benefits",
        )
    )

    # Always compute the matched-keyword list for display/transparency
    search_vocab = set(_VOCAB_LOWER) | {k.lower() for k in profile.keywords}
    job_kw = dedupe_substrings(extract_keywords(haystack, search_vocab))
    cv_kw_lc = {k.lower() for k in profile.keywords}
    matched = sorted(job_kw & cv_kw_lc)

    # Try semantic first
    sem_text = " ".join([
        str(job_row.get("Job Title", "") or ""),
        str(job_row.get("Responsibilities", "") or ""),
        str(job_row.get("Requirements", "") or ""),
    ]).strip()

    score = None
    if profile.cv_text and len(sem_text) >= 80:
        # Cache CV embedding on the profile object
        emb = getattr(profile, "_emb", None)
        if emb is None:
            emb = cv_embedding(profile.cv_text)
            try:
                profile._emb = emb
            except Exception:
                pass
        if emb is not None:
            score = compute_semantic_score(emb, sem_text)

    # Fall back to keyword if semantic unavailable or JD too thin
    if score is None:
        score, _ = _score_keyword(profile, job_row, haystack)

    # Years adjustment (same for both paths, slightly milder for semantic)
    req_years = extract_max_years(haystack)
    if req_years and profile.years is not None:
        if profile.years >= req_years:
            score = min(100, score + 5)
        elif profile.years < req_years - 2:
            score = max(0, score - 10)

    return min(100, max(0, score)), matched


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python cv_match.py path/to/cv.pdf")
        raise SystemExit(2)
    prof = load_cv(sys.argv[1])
    if prof is None:
        raise SystemExit(1)
    print(prof.summary())
    print("Keywords:", sorted(prof.keywords))
