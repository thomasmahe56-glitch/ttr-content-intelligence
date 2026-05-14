"""
Récupère le contexte de style de Thomas depuis Notion :
- 10 derniers transcripts podcast (base Transcript Podcast)
- Contenu des 7 modules de formation (Du coureur blessé au coureur sans douleur)
- Sujets traités dans les 30 derniers jours (base Contenu TTR)
- Patterns de performance depuis performance_patterns.json (généré par sync-my-stats)

Utilisé pour enrichir le prompt Claude avec le vocabulaire, les thèmes réels de Thomas,
et éviter la répétition de sujets récents.
"""
import json
import os
from datetime import datetime, timezone, timedelta
from notion_client import Client
from config import NOTION_API_KEY, NOTION_TRANSCRIPT_DB_ID, NOTION_FORMATION_PAGE_ID, NOTION_DATABASE_ID
from utils.logger import log_info, log_success, log_error

_PATTERNS_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "performance_patterns.json")
)

_notion = Client(auth=NOTION_API_KEY)

# Nombre de caractères max par source pour ne pas exploser le contexte
_TRANSCRIPT_CHARS = 800
_MODULE_CHARS = 600


def fetch_thomas_context() -> str:
    """
    Retourne une chaîne de contexte prête à injecter dans le prompt Claude.
    Combine transcripts + formation en un bloc structuré.
    """
    log_info("Récupération du contexte Notion (transcripts + formation)...")
    parts = []

    transcripts = _fetch_transcripts()
    if transcripts:
        parts.append("## Extraits de transcripts podcast de Thomas\n" + transcripts)

    formation = _fetch_formation()
    if formation:
        parts.append("## Extraits de la formation « Du coureur blessé au coureur sans douleur »\n" + formation)

    if not parts:
        log_error("Aucun contexte Notion récupéré — vérifie les accès de l'intégration.")
        return ""

    log_success(f"Contexte Notion chargé ({len(' '.join(parts))} caractères)")
    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Transcripts
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_transcripts() -> str:
    try:
        response = _notion.databases.query(
            database_id=NOTION_TRANSCRIPT_DB_ID,
            filter={"property": "État", "select": {"equals": "Utilisable"}},
            sorts=[{"timestamp": "created_time", "direction": "descending"}],
            page_size=10,
        )
    except Exception as e:
        log_error(f"Transcripts : {e}")
        return ""

    excerpts = []
    for page in response.get("results", []):
        title = _title_of(page)
        content = _page_text(page["id"], max_chars=_TRANSCRIPT_CHARS)
        if content:
            excerpts.append(f"**{title}**\n{content}")

    return "\n\n---\n\n".join(excerpts)


# ─────────────────────────────────────────────────────────────────────────────
# Formation
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_formation() -> str:
    try:
        blocks = _notion.blocks.children.list(block_id=NOTION_FORMATION_PAGE_ID)
    except Exception as e:
        log_error(f"Formation : {e}")
        return ""

    # Collecte les child_page blocks (modules)
    module_ids = []
    for block in blocks.get("results", []):
        if block["type"] == "child_page":
            title = block["child_page"].get("title", "")
            # Ignore les pages d'idées de structure
            if "idée" not in title.lower() and "structure" not in title.lower():
                module_ids.append((title, block["id"]))

    excerpts = []
    for title, page_id in module_ids:
        content = _page_text(page_id, max_chars=_MODULE_CHARS)
        if content:
            excerpts.append(f"**{title}**\n{content}")

    return "\n\n---\n\n".join(excerpts)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _page_text(page_id: str, max_chars: int = 800) -> str:
    """Extrait le texte brut des blocs d'une page, limité à max_chars."""
    try:
        blocks = _notion.blocks.children.list(block_id=page_id, page_size=20)
    except Exception:
        return ""

    lines = []
    total = 0
    for block in blocks.get("results", []):
        text = _block_text(block)
        if text:
            lines.append(text)
            total += len(text)
            if total >= max_chars:
                break

    return " ".join(lines)[:max_chars]


def _block_text(block: dict) -> str:
    """Extrait le texte d'un bloc Notion (paragraph, heading, bulleted_list_item…)."""
    btype = block.get("type", "")
    content = block.get(btype, {})
    rich_texts = content.get("rich_text", [])
    return "".join(rt.get("plain_text", "") for rt in rich_texts)


def fetch_performance_patterns() -> str:
    """
    Lit performance_patterns.json (généré par sync-my-stats + Claude).
    Si absent, requête Notion comme fallback.
    Retourne un bloc texte prêt à injecter dans le prompt Claude.
    """
    # ── Source primaire : performance_patterns.json ──────────────────────
    if os.path.exists(_PATTERNS_FILE):
        try:
            with open(_PATTERNS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data:
                return _format_patterns_from_json(data)
        except Exception as e:
            log_error(f"Lecture performance_patterns.json : {e}")

    # ── Fallback : requête Notion ─────────────────────────────────────────
    log_info("performance_patterns.json absent — fallback Notion")
    return _fetch_patterns_from_notion()


def _format_patterns_from_json(data: dict) -> str:
    """Formate les patterns JSON en bloc texte pour Claude."""
    n = data.get("total_reels", 0)
    avg_views = data.get("avg_views", 0)
    avg_likes = data.get("avg_likes", 0)
    generated = data.get("generated_at", "")

    lines = [
        f"**{n} Reels @traintorehab analysés** (données du {generated}) :",
        f"Moyenne : {avg_views:,} vues · {avg_likes:,} likes",
        "",
    ]

    top = data.get("top_performers", [])
    if top:
        lines.append("**Top performers :**")
        for i, p in enumerate(top[:5], 1):
            line = f"{i}. {p.get('titre', '')[:50]} — {p.get('vues', 0):,} vues"
            if p.get("hook"):
                line += f"\n   Hook : « {p['hook'][:80]} »"
            lines.append(line)
        lines.append("")

    patterns = data.get("patterns", {})
    if patterns.get("hooks_gagnants"):
        lines.append("**Hooks qui génèrent le plus de vues :**")
        lines += [f"- {h}" for h in patterns["hooks_gagnants"][:5]]
        lines.append("")

    if patterns.get("sujets_performants"):
        lines.append("**Sujets/thèmes les plus performants :**")
        lines += [f"- {s}" for s in patterns["sujets_performants"][:5]]
        lines.append("")

    if patterns.get("formule_gagnante"):
        lines.append(f"**Formule gagnante :** {patterns['formule_gagnante']}")
        lines.append("")

    insights = data.get("insights", [])
    if insights:
        lines.append("**Insights actionnables :**")
        lines += [f"- {ins}" for ins in insights[:3]]
        lines.append("")

    lines += [
        "**À appliquer au script suivant :**",
        "Identifie quels types de hooks, sujets et formats génèrent le plus de vues.",
        "Applique ces patterns gagnants. Privilégie les hooks courts et percutants,",
        "les sujets douleur/reprise/prévention qui dominent ce classement.",
    ]

    log_success(f"Patterns chargés depuis performance_patterns.json ({n} reels)")
    return "\n".join(lines)


def _fetch_patterns_from_notion() -> str:
    """Fallback : interroge la base Contenu TTR pour les stats IG."""
    try:
        resp = _notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={"property": "Vues IG", "number": {"is_not_empty": True}},
            sorts=[{"property": "Vues IG", "direction": "descending"}],
            page_size=50,
        )
    except Exception as e:
        log_error(f"Performance patterns Notion : {e}")
        return ""

    pages = resp.get("results", [])
    if not pages:
        return ""

    performers = []
    for page in pages:
        props = page.get("properties", {})
        views = (props.get("Vues IG") or {}).get("number") or 0
        saves = (props.get("Saves IG") or {}).get("number") or 0
        likes = (props.get("Likes IG") or {}).get("number") or 0
        hook_rts = (props.get("Hook analysé") or {}).get("rich_text", [])
        hook = "".join(rt.get("plain_text", "") for rt in hook_rts)[:100]
        if views > 0:
            performers.append({"title": _title_of(page), "views": views,
                                "saves": saves, "likes": likes, "hook": hook})

    if not performers:
        return ""

    n = len(performers)
    avg_views = sum(p["views"] for p in performers) // n
    avg_saves = sum(p["saves"] for p in performers) // n
    top5 = performers[:5]

    lines = [
        f"**{n} Reels TTR avec stats IG :**",
        f"Moyenne : {avg_views:,} vues · {avg_saves:,} saves",
        "",
        "**Top performers :**",
    ]
    for i, p in enumerate(top5, 1):
        line = f"{i}. {p['title']} — {p['views']:,} vues · {p['saves']:,} saves"
        if p["hook"]:
            line += f"\n   Hook : « {p['hook']} »"
        lines.append(line)

    lines += [
        "",
        "**À appliquer :** identifie et applique les patterns gagnants (hooks courts, sujets douleur/reprise).",
    ]

    log_success(f"Patterns Notion chargés ({n} posts)")
    return "\n".join(lines)


def fetch_recent_topics(days: int = 30) -> str:
    """
    Interroge la base 'Contenu TTR' et retourne les titres des scripts
    générés dans les N derniers jours, prêts à être injectés dans le prompt.
    Retourne une chaîne vide si aucun résultat ou en cas d'erreur.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        response = _notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={
                "timestamp": "created_time",
                "created_time": {"on_or_after": cutoff},
            },
            sorts=[{"timestamp": "created_time", "direction": "descending"}],
        )
    except Exception as e:
        log_error(f"Sujets récents Notion : {e}")
        return ""

    lines = []
    for page in response.get("results", []):
        title = _title_of(page)
        created = page.get("created_time", "")[:10]
        if title:
            lines.append(f"- {title} ({created})")

    log_info(f"{len(lines)} sujet(s) récent(s) récupéré(s) depuis Notion")
    return "\n".join(lines)


def _title_of(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            parts = prop.get("title", [])
            return "".join(p.get("plain_text", "") for p in parts)
    return ""
