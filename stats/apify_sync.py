"""
Sync @traintorehab stats via Apify → base Notion "📊 Performance TTR"
Puis analyse Claude pour extraire les patterns gagnants → performance_patterns.json
"""
import json
import os
from datetime import date, datetime, timezone
from typing import Optional

import anthropic
from notion_client import Client

from config import ANTHROPIC_API_KEY, APIFY_API_KEY, NOTION_API_KEY
from phase1_scraping.apify_scraper import scrape_account_reels
from utils.logger import log_error, log_info, log_success

TTR_ACCOUNT = "traintorehab"
PERF_DB_TITLE = "📊 Performance TTR"
# Page parent : même espace que "Contenu TTR — Analyse Reels"
_PARENT_PAGE_ID = "3608275241468052b02eede76e3ee6ff"

_DIR = os.path.dirname(__file__)
_PATTERNS_FILE = os.path.abspath(os.path.join(_DIR, "..", "performance_patterns.json"))
_DB_CACHE = os.path.join(_DIR, ".perf_db_id")

_notion = Client(auth=NOTION_API_KEY)
_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

PERF_DB_SCHEMA = {
    "Titre": {"title": {}},
    "URL": {"url": {}},
    "Date de publication": {"date": {}},
    "Vues": {"number": {"format": "number"}},
    "Likes": {"number": {"format": "number"}},
    "Commentaires": {"number": {"format": "number"}},
    "Hook détecté": {"rich_text": {}},
    "Statut": {
        "select": {
            "options": [
                {"name": "Analysé", "color": "green"},
                {"name": "À analyser", "color": "gray"},
            ]
        }
    },
}


# ── DB find/create ─────────────────────────────────────────────────────────

def _load_cached_db_id() -> Optional[str]:
    if os.path.exists(_DB_CACHE):
        try:
            return open(_DB_CACHE).read().strip() or None
        except Exception:
            pass
    return None


def _save_cached_db_id(db_id: str) -> None:
    try:
        with open(_DB_CACHE, "w") as f:
            f.write(db_id)
    except Exception:
        pass


def _get_parent_page_id() -> str:
    return _PARENT_PAGE_ID


def _find_or_create_performance_db() -> str:
    """Return the '📊 Performance TTR' DB ID, creating it if absent."""
    # 1. Check local cache
    cached = _load_cached_db_id()
    if cached:
        try:
            _notion.databases.retrieve(cached)
            log_info(f"Base '{PERF_DB_TITLE}' depuis cache : {cached}")
            return cached
        except Exception:
            pass  # Cache stale — search/create

    # 2. Search in workspace
    try:
        results = _notion.search(
            query=PERF_DB_TITLE,
            filter={"value": "database", "property": "object"},
        )
        for obj in results.get("results", []):
            title = "".join(t.get("plain_text", "") for t in obj.get("title", []))
            if "Performance TTR" in title:
                _save_cached_db_id(obj["id"])
                log_info(f"Base '{PERF_DB_TITLE}' trouvée : {obj['id']}")
                return obj["id"]
    except Exception as e:
        log_error(f"Recherche DB performance : {e}")

    # 3. Create
    parent_id = _get_parent_page_id()
    db = _notion.databases.create(
        parent={"type": "page_id", "page_id": parent_id},
        title=[{"type": "text", "text": {"content": PERF_DB_TITLE}}],
        properties=PERF_DB_SCHEMA,
    )
    db_id = db["id"]
    _save_cached_db_id(db_id)
    log_success(f"Base '{PERF_DB_TITLE}' créée : {db_id}")
    return db_id


# ── Notion page helpers ────────────────────────────────────────────────────

def _fetch_existing_urls(db_id: str) -> set:
    urls: set = set()
    cursor = None
    while True:
        kwargs: dict = {"database_id": db_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = _notion.databases.query(**kwargs)
        for page in resp.get("results", []):
            url = (page.get("properties", {}).get("URL") or {}).get("url") or ""
            if url:
                urls.add(url)
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return urls


def _extract_hook(caption: str) -> str:
    """Extract the first sentence of the caption as the hook."""
    if not caption:
        return ""
    for sep in ["\n", "?", "!", "."]:
        idx = caption.find(sep)
        if 5 < idx < 150:
            return caption[: idx + 1].strip()
    return caption[:120].strip()


def _create_reel_page(db_id: str, reel: dict) -> None:
    caption = reel.get("caption", "") or ""
    title = (caption[:80] if caption else reel.get("url", "")[:80]) or "Reel TTR"
    hook = _extract_hook(caption)
    pub_date = (reel.get("timestamp_raw", "") or "")[:10] or None

    props: dict = {
        "Titre": {"title": [{"text": {"content": title}}]},
        "Vues": {"number": reel.get("views") or 0},
        "Likes": {"number": reel.get("likes") or 0},
        "Commentaires": {"number": reel.get("comments") or 0},
        "Statut": {"select": {"name": "Analysé"}},
    }
    url = reel.get("url", "")
    if url:
        props["URL"] = {"url": url}
    if pub_date:
        props["Date de publication"] = {"date": {"start": pub_date}}
    if hook:
        props["Hook détecté"] = {"rich_text": [{"text": {"content": hook}}]}

    _notion.pages.create(parent={"database_id": db_id}, properties=props)


# ── Claude pattern analysis ────────────────────────────────────────────────

def _fix_json_newlines(raw: str) -> str:
    """Replace literal newlines/carriage-returns inside JSON string values."""
    result = []
    in_string = False
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            result.append(c)
            result.append(raw[i + 1])
            i += 2
            continue
        if c == '"':
            in_string = not in_string
        elif in_string and c in ("\n", "\r"):
            result.append(" ")
            i += 1
            continue
        result.append(c)
        i += 1
    return "".join(result)


def _safe(s: str, max_len: int = 80) -> str:
    """Strip characters that break JSON generation (quotes, backslashes, newlines)."""
    if not s:
        return ""
    return s.replace('"', "'").replace("\\", "").replace("\n", " ").replace("\r", "")[:max_len]


def _analyze_with_claude(reels: list) -> str:
    """
    Sends reels data to Claude for pattern extraction.
    Saves result to performance_patterns.json.
    Returns pattern_court for the dashboard.
    """
    summary = [
        {
            "titre": _safe(r.get("caption", "") or ""),
            "hook": _safe(_extract_hook(r.get("caption", "") or "")),
            "vues": r.get("views", 0),
            "likes": r.get("likes", 0),
            "commentaires": r.get("comments", 0),
            "date": (r.get("timestamp_raw", "") or "")[:10],
            "url": r.get("url", ""),
        }
        for r in reels
    ]

    n = len(summary)
    avg_views = sum(r["vues"] for r in summary) // n if n else 0
    avg_likes = sum(r["likes"] for r in summary) // n if n else 0
    avg_comments = sum(r["commentaires"] for r in summary) // n if n else 0
    top5 = sorted(summary, key=lambda r: r["vues"], reverse=True)[:5]

    schema = (
        '{"generated_at":"' + date.today().isoformat() + '",'
        '"total_reels":' + str(n) + ','
        '"avg_views":' + str(avg_views) + ','
        '"avg_likes":' + str(avg_likes) + ','
        '"avg_comments":' + str(avg_comments) + ','
        '"top_performers":[{"titre":"...","vues":0,"hook":"...","url":"..."}],'
        '"patterns":{"hooks_gagnants":["...","..."],"sujets_performants":["...","..."],"formule_gagnante":"..."},'
        '"insights":["...","...","..."],'
        '"pattern_court":"..."}'
    )
    prompt = (
        f"Tu analyses les performances des Reels Instagram de @traintorehab "
        f"(kiné-coach running, niche douleur/course à pied).\n\n"
        f"Voici les {n} derniers Reels avec leurs stats :\n"
        f"{json.dumps(summary, ensure_ascii=False)}\n\n"
        f"Top 5 par vues : {json.dumps(top5, ensure_ascii=False)}\n\n"
        f"Retourne UNIQUEMENT ce JSON valide (une seule ligne, pas de saut de ligne "
        f"dans les valeurs string, pas de markdown) :\n{schema}"
    )

    resp = _claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()

    # Extraction robuste : prend ce qui est entre le premier { et le dernier }
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        log_error("Claude n'a pas retourné de JSON pour les patterns")
        return ""
    raw = raw[start:end]

    raw = _fix_json_newlines(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log_error(f"JSON patterns invalide : {e}")
        return ""

    with open(_PATTERNS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log_success(f"Patterns sauvegardés → {_PATTERNS_FILE}")

    return data.get("pattern_court", "")


# ── Main ───────────────────────────────────────────────────────────────────

async def sync_ttr_stats_via_apify() -> dict:
    """
    Scrape @traintorehab via Apify, alimente '📊 Performance TTR' dans Notion,
    analyse les patterns via Claude et sauvegarde performance_patterns.json.
    Retourne {apify_reels, created, skipped, errors, pattern_insight}.
    """
    db_id = _find_or_create_performance_db()

    log_info(f"Scraping @{TTR_ACCOUNT} via Apify (top 50)...")
    reels = await scrape_account_reels(TTR_ACCOUNT, APIFY_API_KEY, top=50)
    log_info(f"{len(reels)} Reels TTR récupérés via Apify")

    existing_urls = _fetch_existing_urls(db_id)
    new_reels = [r for r in reels if r.get("url") not in existing_urls]
    skipped = len(reels) - len(new_reels)

    created = errors = 0
    for reel in new_reels:
        try:
            _create_reel_page(db_id, reel)
            created += 1
            log_success(f"Page créée : {reel.get('url', '')} ({reel.get('views', 0)} vues)")
        except Exception as e:
            errors += 1
            log_error(f"Erreur création page Notion : {e}")

    pattern_insight = ""
    if reels:
        log_info("Analyse des patterns via Claude...")
        try:
            pattern_insight = _analyze_with_claude(reels)
        except Exception as e:
            log_error(f"Analyse Claude patterns : {e}")

    return {
        "apify_reels": len(reels),
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "pattern_insight": pattern_insight,
    }
