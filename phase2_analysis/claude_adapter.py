import json
import anthropic
from config import ANTHROPIC_API_KEY, TTR_NICHE_CONTEXT
from utils.logger import log_info, log_success
from phase2_analysis.notion_context import fetch_thomas_context, fetch_recent_topics, fetch_performance_patterns

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

ADAPTATION_PROMPT_TEMPLATE = """
{niche_context}

---

## Contexte de style — Vocabulaire et thèmes réels de Thomas

{thomas_context}

---

## Sujets déjà traités (30 derniers jours)

{recent_topics_section}

---

{performance_section}## Analyse du Reel source (@{account})

```json
{gemini_analysis}
```

---

## Tâche

À partir de cette analyse, génère un script Reel clé en main ET une caption Instagram pour TrainToRehab.
Adapte le pattern identifié à la niche kiné-coach running **en utilisant le vocabulaire exact,
les concepts et le ton des transcripts et de la formation de Thomas ci-dessus**.

Si un concept de la formation est pertinent (ex: modèle capacité/contrainte, bilan du coureur),
intègre-le naturellement dans le script.

Pour la caption TTR, inspire-toi de la caption originale (si présente dans l'analyse) mais adapte-la
avec le style et le vocabulaire de Thomas : accroche forte en 1ère ligne, 2-3 phrases de valeur,
emojis pertinents (running / kiné / corps), appel à l'action final engageant, 5-8 hashtags TTR
intégrés à la fin.

Réponds avec ce JSON exact :

{{
  "titre_interne": "titre court pour identifier ce script (ex: 'Douleur genou post-run')",
  "script": {{
    "hook": "texte exact de l'accroche (0-3s)",
    "developpement": [
      "étape 1 : ...",
      "étape 2 : ...",
      "étape 3 : ..."
    ],
    "cta": "call-to-action final exact"
  }},
  "caption_ttr": "caption Instagram complète adaptée TTR — accroche forte ligne 1, développement 2-3 phrases, CTA, hashtags intégrés",
  "concepts_formation_utilises": ["liste des concepts TTR intégrés, vide si aucun"],
  "indications_tournage": {{
    "format_camera": "face caméra / voix-off / terrain / cabinet kiné / autre",
    "décor_recommandé": "description",
    "sous_titres": true,
    "rythme": "rapide / moyen / lent",
    "durée_cible": "durée en secondes"
  }},
  "hashtags_suggeres": ["liste de 5-8 hashtags"],
  "pourquoi_ca_marche": "explication courte"
}}

Retourne uniquement le JSON valide, sans commentaires.
"""


def adapt_to_ttr(gemini_analysis: dict, account: str) -> dict:
    """
    Enrichit le prompt Claude avec :
    - contexte style Thomas (transcripts + formation)
    - sujets récents (30 jours) pour éviter les répétitions
    """
    thomas_context = fetch_thomas_context()
    if not thomas_context:
        log_info("Contexte Notion vide — génération sans enrichissement style")
        thomas_context = "(contexte indisponible — accès Notion à configurer)"

    recent = fetch_recent_topics(days=30)
    if recent:
        recent_topics_section = (
            f"{recent}\n\n"
            "Tu peux t'inspirer de ces thèmes mais **trouve un angle différent ou un sujet nouveau**. "
            "Tout sujet de plus de 30 jours est à nouveau disponible."
        )
    else:
        recent_topics_section = "Aucun script généré dans les 30 derniers jours — tu as carte blanche."

    patterns = fetch_performance_patterns()
    if patterns:
        performance_section = (
            "## Feedback loop — Performances réelles de tes Reels TTR\n\n"
            "Voici les performances de mes posts TTR publiés :\n\n"
            + patterns
            + "\n\n---\n\n"
        )
    else:
        performance_section = ""

    log_info("Adaptation du pattern via Claude Sonnet (contexte + sujets récents + feedback loop)...")

    prompt = ADAPTATION_PROMPT_TEMPLATE.format(
        niche_context=TTR_NICHE_CONTEXT,
        thomas_context=thomas_context,
        recent_topics_section=recent_topics_section,
        performance_section=performance_section,
        gemini_analysis=json.dumps(gemini_analysis, ensure_ascii=False, indent=2),
        account=account,
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip().removeprefix("```json").removesuffix("```").strip()

    try:
        script = json.loads(raw)
    except json.JSONDecodeError:
        script = {"raw_response": raw}

    log_success("Script TTR généré par Claude (avec style Thomas)")
    return script
