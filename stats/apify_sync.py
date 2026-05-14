"""
Synchronise les stats des Reels @traintorehab publiés via Apify Instagram Scraper.
Alternative sans Instagram Graph API : utilise les données publiques Apify.
Stats disponibles : vues, likes, commentaires (pas de saves ni de reach via Apify).
"""
from datetime import datetime, timezone
from typing import Optional

from notion_client import Client

from config import NOTION_API_KEY, NOTION_DATABASE_ID, APIFY_API_KEY
from phase1_scraping.apify_scraper import scrape_account_reels
from utils.logger import log_info, log_success, log_error

TTR_ACCOUNT = "traintorehab"

_notion = Client(auth=NOTION_API_KEY)
_STAT_PROPS = {"Vues IG": "number", "Likes IG": "number", "Commentaires IG": "number"}
_props_ready = False


def _ensure_props() -> None:
    global _props_ready
    if _props_ready:
        return
    try:
        db = _notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
        existing = db.get("properties", {})
        missing = {k: {"number": {}} for k in _STAT_PROPS if k not in existing}
        if missing:
            _notion.databases.update(database_id=NOTION_DATABASE_ID, properties=missing)
        _props_ready = True
    except Exception as e:
        log_error(f"Props stats Apify : {e}")


def _fetch_notion_pages() -> list:
    pages = []
    cursor = None
    while True:
        kwargs: dict = {"database_id": NOTION_DATABASE_ID, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = _notion.databases.query(**kwargs)
        pages.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return pages


def _date_gen_of(page: dict) -> Optional[datetime]:
    date_prop = page.get("properties", {}).get("Date de génération", {})
    start = (date_prop.get("date") or {}).get("start") or page.get("created_time", "")[:10]
    if not start:
        return None
    try:
        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _title_of(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(p.get("plain_text", "") for p in prop.get("title", []))
    return ""


def _match(timestamp_raw: str, pages: list) -> Optional[dict]:
    """Match un Reel TTR (date publication) à une page Notion (Date de génération)."""
    if not timestamp_raw:
        return None
    try:
        reel_dt = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
        if not reel_dt.tzinfo:
            reel_dt = reel_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

    candidates = []
    for page in pages:
        pg_dt = _date_gen_of(page)
        if pg_dt is None:
            continue
        delta = (reel_dt - pg_dt).days  # positif = reel publié après la génération
        if -3 <= delta <= 30:
            candidates.append((abs(delta), page))

    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x[0])[0][1]


def _update_stats(page_id: str, reel: dict) -> None:
    _notion.pages.update(
        page_id=page_id,
        properties={
            "Vues IG":         {"number": reel.get("views") or 0},
            "Likes IG":        {"number": reel.get("likes") or 0},
            "Commentaires IG": {"number": reel.get("comments") or 0},
        },
    )


def _compute_pattern_insight(performers: list) -> str:
    """Retourne un insight court sur les top posts pour affichage dashboard."""
    if not performers:
        return ""
    top = performers[:3]
    titles = [p["title"][:40] for p in top if p.get("title")]
    hooks = [p["hook"][:70] for p in top if p.get("hook")]
    parts = []
    if titles:
        parts.append("Top posts : " + " · ".join(titles[:2]))
    if hooks:
        parts.append(f"Hook gagnant : « {hooks[0]} »")
    return " — ".join(parts)


async def sync_ttr_stats_via_apify() -> dict:
    """
    Scrape @traintorehab via Apify, matche avec Notion, met à jour Vues/Likes/Commentaires.
    Retourne {apify_reels, updated, skipped, errors, pattern_insight}.
    """
    _ensure_props()

    log_info(f"Scraping @{TTR_ACCOUNT} via Apify pour feedback loop stats...")
    reels = await scrape_account_reels(TTR_ACCOUNT, APIFY_API_KEY, top=50)
    log_info(f"{len(reels)} Reels TTR récupérés via Apify")

    notion_pages = _fetch_notion_pages()

    updated = skipped = errors = 0
    performers = []

    for reel in reels:
        ts = reel.get("timestamp_raw", "")
        page = _match(ts, notion_pages)
        if page is None:
            skipped += 1
            log_info(f"Pas de match Notion pour {reel.get('url', '')} ({ts})")
            continue
        try:
            _update_stats(page["id"], reel)
            updated += 1
            hook_rts = (page.get("properties", {}).get("Hook analysé") or {}).get("rich_text", [])
            hook = "".join(rt.get("plain_text", "") for rt in hook_rts)
            performers.append({
                "title": _title_of(page),
                "hook": hook,
                "views": reel.get("views", 0),
            })
            log_success(f"Stats sync : {reel.get('url', '')} ({reel.get('views', 0)} vues)")
        except Exception as e:
            errors += 1
            log_error(f"Erreur update Notion : {e}")

    performers.sort(key=lambda p: p["views"], reverse=True)

    return {
        "apify_reels": len(reels),
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "pattern_insight": _compute_pattern_insight(performers),
    }
