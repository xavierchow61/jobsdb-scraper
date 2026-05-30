"""Gemini-powered job analysis features.

Three public entry points, all with Supabase caching:

    summarize_jd(supabase, user_id, job_row)
        → "• 重點 1\\n• 重點 2 …"
        Auto-cache, ~150 tokens of LLM output.

    analyze_mismatch(supabase, user_id, cv_keywords, cv_years, job_row)
        → {
            "matched_skills": [...],
            "missing_skills": [...],
            "mismatch_reason": "...",
            "fit_score": int(0-100),
          }

    generate_cover_letter(supabase, user_id, cv_keywords, cv_years, job_row)
        → str (~300 words English)

Cache lives in Supabase `job_analysis` table keyed by (user_id, jd_number).
Re-running an analysis on the same job re-uses the cached row (no LLM call).
Force refresh by passing force=True.
"""

import json
import os

import streamlit as st


_MODEL_NAME = "gemini-2.5-flash"   # Free, fast, plenty for short tasks
_model = None
_model_init_err = None


# ============================================================
# Gemini client
# ============================================================

def _get_api_key():
    """Read Gemini key from st.secrets[gemini].api_key or env var."""
    try:
        return st.secrets["gemini"]["api_key"]
    except (KeyError, FileNotFoundError, AttributeError):
        pass
    return os.environ.get("GEMINI_API_KEY", "")


def _get_model():
    global _model, _model_init_err
    if _model is not None:
        return _model
    if _model_init_err is not None:
        return None
    key = (_get_api_key() or "").strip()
    if not key:
        _model_init_err = "Gemini API key 未設定（admin 需於 secrets 加 [gemini].api_key）"
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        _model = genai.GenerativeModel(_MODEL_NAME)
        return _model
    except Exception as e:
        _model_init_err = f"Gemini 載入失敗: {e}"
        return None


def is_available():
    return _get_model() is not None


def availability_reason():
    """Human-readable string describing why AI isn't available, if so."""
    _get_model()
    return _model_init_err or ""


def _call_llm(prompt, max_chars=4000):
    model = _get_model()
    if model is None:
        return None, "Gemini 未設定"
    if len(prompt) > 12000:
        prompt = prompt[:12000]
    try:
        res = model.generate_content(prompt)
        text = (res.text or "").strip()
        return text[:max_chars], None
    except Exception as e:
        return None, f"Gemini 呼叫失敗: {e}"


# ============================================================
# Supabase cache
# ============================================================

def _get_cached(supabase, user_id, jd_number):
    """Return cached job_analysis row or None."""
    if not supabase or not user_id or not jd_number:
        return None
    try:
        res = (
            supabase.table("job_analysis")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("jd_number", str(jd_number))
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as e:
        print(f"  [ai] cache read failed: {e}")
        return None


def _upsert_cache(supabase, user_id, jd_number, fields):
    if not supabase or not user_id or not jd_number:
        return
    from datetime import datetime, timezone
    payload = {
        "user_id": str(user_id),
        "jd_number": str(jd_number),
        **fields,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        supabase.table("job_analysis").upsert(payload).execute()
    except Exception as e:
        print(f"  [ai] cache write failed: {e}")


# ============================================================
# Field helpers (row dicts come from CSV or Supabase — different key cases)
# ============================================================

def _get(row, *keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return v
    return ""


def _jd_meta(row):
    return {
        "jd_number":      str(_get(row, "JD Number", "jd_number") or ""),
        "title":          _get(row, "Job Title", "job_title"),
        "company":        _get(row, "Company", "company"),
        "salary":         _get(row, "Salary", "salary"),
        "location":       _get(row, "Location", "location"),
        "responsibilities": (_get(row, "Responsibilities", "responsibilities") or "")[:2000],
        "requirements":   (_get(row, "Requirements", "requirements") or "")[:2000],
        "benefits":       (_get(row, "Benefits", "benefits") or "")[:1000],
    }


# ============================================================
# Feature 1: JD summary
# ============================================================

def summarize_jd(supabase, user_id, job_row, force=False):
    meta = _jd_meta(job_row)
    if not meta["jd_number"]:
        return None, "缺 JD Number"

    if not force:
        cached = _get_cached(supabase, user_id, meta["jd_number"])
        if cached and cached.get("jd_summary"):
            return cached["jd_summary"], None

    prompt = f"""你係招聘顧問，請用繁體中文書面語為以下職位寫 4-6 個 bullet 摘要。
每個 bullet 不過 30 字。涵蓋：
- 主要職責（2-3 條）
- 關鍵 hard skill / qualification
- 年資 / 學歷要求（如 JD 有提）
- 福利亮點（如 JD 有提）

職位：{meta['title']}
公司：{meta['company']}
薪酬：{meta['salary']}
地點：{meta['location']}

【職責】
{meta['responsibilities']}

【要求】
{meta['requirements']}

【福利】
{meta['benefits']}

請只輸出 bullet（每行以「• 」開頭），不要 preamble 或 closing。"""

    text, err = _call_llm(prompt, max_chars=2000)
    if err:
        return None, err
    _upsert_cache(supabase, user_id, meta["jd_number"], {"jd_summary": text})
    return text, None


# ============================================================
# Feature 2: mismatch analysis
# ============================================================

def analyze_mismatch(supabase, user_id, cv_keywords, cv_years, job_row, force=False):
    meta = _jd_meta(job_row)
    if not meta["jd_number"]:
        return None, "缺 JD Number"

    if not force:
        cached = _get_cached(supabase, user_id, meta["jd_number"])
        if cached and cached.get("mismatch_analysis"):
            return cached["mismatch_analysis"], None

    kw_str = ", ".join(cv_keywords[:30]) if cv_keywords else "(未提供 keyword)"
    prompt = f"""你係招聘配對顧問。比較以下用戶 CV 同職位 JD，輸出純 JSON object（不要 markdown fence、不要其他文字）。

【職位】{meta['title']} @ {meta['company']}

【JD 職責】
{meta['responsibilities']}

【JD 要求】
{meta['requirements']}

【用戶 CV】
經驗：{cv_years or '?'} 年
關鍵字：{kw_str}

請輸出以下 JSON schema（用繁體中文書面語）：
{{
  "matched_skills":   ["..."],   // CV 同 JD 都有嘅關鍵字，最多 8 個
  "missing_skills":   ["..."],   // JD 有但 CV 無嘅關鍵 skill，最多 5 個
  "mismatch_reason":  "...",     // 一句總結為何 user 可能配對唔強（≤ 50 字）
  "strength_summary": "...",     // 一句總結 user 喺呢個 job 嘅優勢（≤ 50 字）
  "fit_score":        0          // 0-100 整數，根據經驗 + skill match
}}"""

    text, err = _call_llm(prompt, max_chars=2000)
    if err:
        return None, err

    # Strip optional markdown fences
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # remove first line + last fence
        parts = cleaned.split("\n", 1)
        if len(parts) > 1:
            cleaned = parts[1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    cleaned = cleaned.strip()
    if cleaned.startswith("json"):
        cleaned = cleaned[4:].lstrip()

    try:
        obj = json.loads(cleaned)
    except Exception as e:
        return None, f"AI 返回無效 JSON: {e}\n原文: {text[:300]}"

    _upsert_cache(supabase, user_id, meta["jd_number"], {"mismatch_analysis": obj})
    return obj, None


# ============================================================
# Feature 3: cover letter
# ============================================================

def generate_cover_letter(supabase, user_id, cv_keywords, cv_years, job_row, force=False):
    meta = _jd_meta(job_row)
    if not meta["jd_number"]:
        return None, "缺 JD Number"

    if not force:
        cached = _get_cached(supabase, user_id, meta["jd_number"])
        if cached and cached.get("cover_letter"):
            return cached["cover_letter"], None

    kw_str = ", ".join(cv_keywords[:20]) if cv_keywords else ""
    prompt = f"""Write a professional cover letter (300-400 words, English) for the
following job. Use the candidate's CV summary to highlight relevant
experience. Tone: professional yet warm; concrete examples preferred.

Job title: {meta['title']}
Company:   {meta['company']}

Job responsibilities:
{meta['responsibilities']}

Job requirements:
{meta['requirements']}

Candidate CV summary:
- Years of experience: {cv_years or 'unspecified'}
- Key skills/keywords: {kw_str}

Output ONLY the letter body (no letterhead, no signature placeholder,
no "Dear Hiring Manager" line — just paragraphs ready to paste).
Highlight 3 specific qualifications that match the JD's top requirements."""

    text, err = _call_llm(prompt, max_chars=3000)
    if err:
        return None, err
    _upsert_cache(supabase, user_id, meta["jd_number"], {"cover_letter": text})
    return text, None
