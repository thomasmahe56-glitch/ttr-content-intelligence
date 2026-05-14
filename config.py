from dotenv import load_dotenv
import os

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
APIFY_API_KEY = os.getenv("APIFY_API_KEY", "")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID", "me")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_TRANSCRIPT_DB_ID = os.getenv("NOTION_TRANSCRIPT_DB_ID", "3378275241468037884be8b66cfa0741")
NOTION_FORMATION_PAGE_ID = os.getenv("NOTION_FORMATION_PAGE_ID", "31982752414680cf9a80c8fb65864ac7")


DOWNLOADS_DIR = os.getenv("DOWNLOADS_DIR", "./downloads")
MAX_REELS_PER_ACCOUNT = int(os.getenv("MAX_REELS_PER_ACCOUNT", 10))

TTR_NICHE_CONTEXT = """
Tu es expert en contenu pour TrainToRehab, une marque fondée par Thomas Mahé.
Cible : coureurs blessés ou en prévention, 25-45 ans, cherchent à reprendre sans se blesser.
Ton : pédagogue, rassurant, direct, crédible (kiné + coach running).
Mots-clés niche : blessure running, reprise course, douleur genou/tendon, programme kiné, prévention fracture de fatigue.
Format Reel TTR : accroche douleur/problème → solution concrète → preuve → CTA programme/consultation.
"""
