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
_last_err = ""   # Last init error message (NOT cached as a permanent flag)


# ============================================================
# Gemini client
# ============================================================

def _get_api_key():
    """Read Gemini key. Try several conventional locations so a
    misplaced secret still works."""
    # 1. st.secrets[gemini].api_key (preferred)
    for section_key, leaf in (
        ("gemini", "api_key"),
        ("gemini", "key"),
        ("google_ai", "api_key"),
        ("google", "api_key"),
    ):
        try:
            v = st.secrets[section_key][leaf]
            if v:
                return str(v).strip()
        except (KeyError, FileNotFoundError, AttributeError):
            continue

    # 2. Flat keys at the top of secrets
    for flat in ("GEMINI_API_KEY", "gemini_api_key", "GOOGLE_API_KEY"):
        try:
            v = st.secrets[flat]
            if v:
                return str(v).strip()
        except (KeyError, FileNotFoundError, AttributeError):
            continue

    # 3. Environment variable
    return (os.environ.get("GEMINI_API_KEY") or "").strip()


def _get_model():
    """Return a Gemini model instance, or None on failure.

    NOTE: previous version cached _model_init_err which made the function
    return None forever once a single init failed — even after the user
    fixed their secrets and Streamlit reloaded the module hot. Now we
    only cache the success (the model object); errors retry every call
    so a Save-secrets is reflected immediately.
    """
    global _model, _last_err
    if _model is not None:
        return _model
    key = _get_api_key()
    if not key:
        _last_err = (
            "Gemini API key 未設定。請於 Streamlit Cloud → Settings → "
            "Secrets 加上 [gemini] api_key = \"AIzaSy...\"，Save 後等 "
            "30 秒 redeploy。如已加但仍失敗，去 Manage app → ⋮ Reboot。"
        )
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        _model = genai.GenerativeModel(_MODEL_NAME)
        _last_err = ""
        return _model
    except ImportError:
        _last_err = (
            "google-generativeai 套件未安裝。確認 requirements.txt 已包含 "
            "google-generativeai 同等 Streamlit Cloud 重新 install dependencies。"
        )
        return None
    except Exception as e:
        _last_err = f"Gemini 載入失敗：{e}"
        return None


def is_available():
    return _get_model() is not None


def availability_reason():
    """Human-readable string describing why AI isn't available."""
    _get_model()   # refresh _last_err
    return _last_err


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
    prompt = f"""你是資深招聘配對顧問。比較以下用戶 CV 與職位 JD，給出明確的申請建議。

主要任務：解釋**為何建議申請**這份工作（如分數低，請誠實說明原因）。
側重 actionable reasoning，讓用戶清楚決定是否花時間申請。

只輸出純 JSON object（無 markdown fence、無其他文字）。

【職位】{meta['title']} @ {meta['company']}

【JD 職責】
{meta['responsibilities']}

【JD 要求】
{meta['requirements']}

【用戶 CV】
經驗：{cv_years or '?'} 年
關鍵字：{kw_str}

請輸出以下 JSON schema（**所有文字用繁體中文書面語**）：

{{
  "fit_score": 0,              // 0-100 整數
  "verdict": "...",            // 一個：建議申請 / 可考慮 / 不太建議
  "why_apply": [               // 為何建議申請，3-5 點具體理由
    "理由 1（具體指出 user 哪 1-2 個經驗／技能直接對應 JD 哪項要求，配以細節）",
    "..."
  ],
  "talking_points": "...",     // 1-2 句：申請時 cover letter／面試應突出的角度
  "matched_skills": ["..."],   // CV 與 JD 都具備的關鍵字／技能，最多 8 個
  "missing_skills": ["..."],   // JD 有但 CV 似乎沒有的關鍵 skill，最多 5 個
  "concerns": "..."            // 一句：申請時應留意的地方／可能的 mismatch（≤ 60 字）
}}

如果用戶真的不適合這份工作：
- verdict = "不太建議"
- why_apply 仍須列 1-2 個「適合的角度」（即使分數低），讓用戶若選擇申請時有一些頭緒
- concerns 詳述主要 gap"""

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
