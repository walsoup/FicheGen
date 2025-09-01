import os
import re
import json
import time
import datetime
import streamlit as st
from dotenv import load_dotenv
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import pdfplumber
from openai import OpenAI
import google.generativeai as genai
from streamlit_option_menu import option_menu

load_dotenv()

# Prefer Streamlit secrets (TOML on Streamlit Cloud) with env fallback
def _get_secret(name: str, *nested_sections: str) -> str:
    """Fetch a secret from st.secrets, supporting optional nested sections, with os.getenv fallback."""
    try:
        # flat key at root
        if name in st.secrets:
            return str(st.secrets[name])
        # support a few common nested sections: [api], [keys], [secrets]
        for sect in ("api", "keys", "secrets") + nested_sections:
            try:
                sect_dict = st.secrets.get(sect)  # type: ignore[attr-defined]
            except Exception:
                sect_dict = None
            if isinstance(sect_dict, dict) and name in sect_dict:
                return str(sect_dict[name])
    except Exception:
        pass
    return os.getenv(name, "")

# =========================
# Models and defaults (per your list)
# =========================
OPENROUTER_MODELS = [
    "deepseek/deepseek-chat-v3.1:free",
    "deepseek/deepseek-r1-distill-llama-70b:free",
    "deepseek/deepseek-r1:free",
    "mistralai/mistral-small-3.2-24b-instruct:free",
    "meta-llama/llama-4-scout:free"
]
GEMINI_MODEL = "gemini-2.5-flash"
TABLE_OF_CONTENTS_PAGES_DEFAULT = 5

# =========================
# PDF class (teal default + gutter duration)
# =========================
class PDF(FPDF):
    PALETTES = {
        "teal": {
            "primary": (0, 128, 128),
            "secondary": (255, 127, 80),
            "accent": (255, 127, 80),
            "text": (0, 0, 0),
            "bg_light": (245, 245, 245),
            "gutter_bg": (255, 192, 0),
        },
        "pro": {
            "primary": (34, 49, 63),
            "secondary": (69, 170, 242),
            "accent": (46, 204, 113),
            "text": (51, 51, 51),
            "bg_light": (245, 245, 245),
        },
        "study": {
            "primary": (44, 62, 80),
            "secondary": (243, 156, 18),
            "accent": (231, 76, 60),
            "text": (51, 51, 51),
            "bg_light": (236, 240, 241),
        }
    }

    def __init__(
        self,
        doc_type="student",
        base_template="teal",
        page_format="A4",
        orientation="P",
        margins=(15, 15, 20),
        base_font_size=12,
        line_spacing=1.15,
        show_cover=False,
        cover_meta=None,
        watermark_text="",
        *args, **kwargs
    ):
        super().__init__(orientation=orientation, unit="mm", format=page_format, *args, **kwargs)
        self.doc_type = doc_type
        self.base_template = base_template if base_template in self.PALETTES else "teal"
        self.colors = self.PALETTES[self.base_template]

        self.page_title = "Fiche de Révision" if doc_type == "student" else "Fiche Pédagogique"

        self.base_font_size = base_font_size
        self.line_spacing = line_spacing
        self.set_auto_page_break(True, margin=15)
        self.set_left_margin(margins[0])
        self.set_right_margin(margins[1])
        self.set_top_margin(margins[2])

        self.show_cover = show_cover
        self.cover_meta = cover_meta or {}
        self.watermark_text = watermark_text
        self._suppress_header = False

        # Gutter goodies for 'teal'
        self.gutter_w = 22
        self._phase_duration = None
        self._printed_gutter_for_phase = False

        # Fonts
        try:
            self.add_font("DejaVu", "", "DejaVuSans.ttf", uni=True)
            self.add_font("DejaVu", "B", "DejaVuSans-Bold.ttf", uni=True)
            self.set_font("DejaVu", "", self.base_font_size)
            self.font_family = "DejaVu"
        except RuntimeError:
            st.warning("DejaVu fonts not found. Falling back to Arial (limited unicode).")
            self.set_font("Arial", "", self.base_font_size)
            self.font_family = "Arial"

    def header(self):
        if self._suppress_header:
            return

        if self.base_template == "teal":
            self.set_font(self.font_family, 'B', 16)
            self.set_text_color(*self.colors["primary"])
            self.cell(0, 12, self.page_title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
            self.ln(2)
            self.set_draw_color(*self.colors["primary"])
            self.set_line_width(0.6)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(6)
        else:
            self.set_font(self.font_family, 'B', int(self.base_font_size * 1.8))
            self.set_text_color(*self.colors["primary"])
            self.cell(0, 10, self.page_title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')

            if self.base_template == "pro":
                self.set_line_width(0.5)
                self.set_draw_color(*self.colors["secondary"])
                self.line(self.l_margin, self.get_y() + 2, self.w - self.r_margin, self.get_y() + 2)
            else:  # study
                self.set_fill_color(*self.colors["secondary"])
                self.cell(0, 2, "", border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)

            self.ln(8)

        if self.watermark_text:
            self.set_text_color(200, 200, 200)
            self.set_font(self.font_family, 'B', int(self.base_font_size * 2.0))
            y = self.get_y() + 2
            self.set_xy(self.l_margin, y)
            self.cell(0, 10, self.watermark_text, align='C')
            self.set_text_color(*self.colors.get("text", (0, 0, 0)))
            self.set_font(self.font_family, '', self.base_font_size)
            self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font(self.font_family, '', max(8, int(self.base_font_size * 0.7)))
        self.set_text_color(130, 130, 130)
        self.cell(0, 8, f'Page {self.page_no()}', align='C')

    def write_kv_pair(self, label, value):
        self.set_font(self.font_family, 'B', int(self.base_font_size * 0.95))
        self.set_text_color(*self.colors["primary"])
        self.cell(45, 7 * self.line_spacing, f"{label} :", border=0)
        self.set_font(self.font_family, '', int(self.base_font_size * 0.95))
        self.set_text_color(*self.colors.get("text", (0, 0, 0)))
        self.multi_cell(0, 7 * self.line_spacing, value, border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def write_section_header(self, title):
        if self.base_template == "teal":
            self._phase_duration = None
            self._printed_gutter_for_phase = False
            self.set_font(self.font_family, 'B', 14)
            self.set_text_color(*self.colors["secondary"])
            self.multi_cell(0, 9 * self.line_spacing, title.strip(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(2)
        else:
            self.set_font(self.font_family, 'B', int(self.base_font_size * 1.2))
            self.set_text_color(*self.colors["secondary"])
            self.set_fill_color(*self.colors["bg_light"])
            self.multi_cell(0, 9 * self.line_spacing, f" {title.strip()} ", border='B' if self.base_template == 'study' else 0, fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_draw_color(*self.colors["secondary"])
            self.ln(3)

    def write_subsection_header(self, title):
        if self.base_template == "teal":
            self.set_font(self.font_family, 'B', 12)
            self.set_text_color(*self.colors["primary"])
            self.multi_cell(0, 8 * self.line_spacing, title.strip(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(1)
        else:
            self.set_font(self.font_family, 'B', int(self.base_font_size * 1.05))
            self.set_text_color(*self.colors["accent"])
            self.multi_cell(0, 8 * self.line_spacing, title.strip(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(1)

    def start_phase(self, title: str, minutes: str | None):
        if self.base_template == "teal":
            self._phase_duration = f"{minutes} min" if minutes else None
            self._printed_gutter_for_phase = False
            self.set_font(self.font_family, 'B', 12)
            self.set_text_color(*self.colors["primary"])
            self.multi_cell(0, 8 * self.line_spacing, title.strip(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(1)
        else:
            self.write_subsection_header(f"{title.strip()}" + (f" ({minutes} min)" if minutes else ""))

    def write_bullet(self, text: str):
        if self.base_template == "teal":
            if self._phase_duration and not self._printed_gutter_for_phase:
                self.set_fill_color(*self.colors["gutter_bg"])
                self.set_text_color(*self.colors["secondary"])
                self.set_font(self.font_family, 'B', 10)
                self.cell(self.gutter_w, 8, self._phase_duration, border=0, ln=0, align='C', fill=True)
                self._printed_gutter_for_phase = True
            else:
                self.cell(self.gutter_w, 8, '', border=0, ln=0)

            right_w = self.w - self.r_margin - (self.l_margin + self.gutter_w)
            self.set_text_color(0, 0, 0)
            self.set_font(self.font_family, '', 11)
            bullet_sentence = f"• {text.strip()}"
            self.multi_cell(right_w, 8, bullet_sentence, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(1)
        else:
            self.set_font(self.font_family, '', int(self.base_font_size * 0.95))
            self.set_text_color(*self.colors.get("text", (0, 0, 0)))
            bullet = '✓' if self.base_template == 'study' else '•'
            self.multi_cell(0, 7 * self.line_spacing, f"  {bullet}  {text.strip()}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(0.5)

    def write_paragraph(self, text: str):
        self.set_font(self.font_family, '', int(self.base_font_size * 0.95))
        self.set_text_color(*self.colors.get("text", (0, 0, 0)))
        self.multi_cell(0, 7 * self.line_spacing, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1.5)

    def add_cover_page(self):
        self._suppress_header = True
        self.add_page()
        self._suppress_header = False

        self.set_text_color(*self.colors["primary"])
        self.set_font(self.font_family, 'B', int(self.base_font_size * 2.2))
        self.ln(40)
        self.cell(0, 12, self.page_title, align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_font(self.font_family, '', int(self.base_font_size * 1.1))
        self.set_text_color(*self.colors.get("text", (0, 0, 0)))
        self.ln(6)
        for key, label in [("title", "Sujet"), ("class_level", "Classe"), ("duration", "Durée")]:
            value = self.cover_meta.get(key, "")
            if value:
                self.cell(0, 10, f"{label}: {value}", align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        author = self.cover_meta.get("author", "")
        date_str = self.cover_meta.get("date", "")
        if author or date_str:
            self.ln(4)
            self.set_text_color(120, 120, 120)
            footer_line = f"{author}" + (f" — {date_str}" if date_str else "")
            self.cell(0, 8, footer_line, align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.ln(10)
        self.set_fill_color(*self.colors.get("secondary", (0, 0, 0)))
        self.cell(0, 4, "", border=0, fill=True)

    def add_content(self, text_content):
        if self.show_cover:
            self.add_cover_page()
        self.add_page()

        self._phase_duration = None
        self._printed_gutter_for_phase = False

        lines = text_content.split('\n')
        for raw in lines:
            line = raw.strip()
            if not line:
                self.ln(1)
                continue

            if line.startswith('## '):
                self.write_section_header(line[3:])
                continue

            m_phase = re.match(r'^(?:###|####)\s*(.+?)\s*(?:[—\-]\s*(\d+)\s*min|\((\d+)\s*min\))?\s*$', line)
            if m_phase:
                title = m_phase.group(1)
                minutes = m_phase.group(2) or m_phase.group(3)
                self.start_phase(title, minutes)
                continue

            if line.startswith('- ') or line.startswith('* '):
                self.write_bullet(line[2:])
                continue

            m_lv = re.match(r'^(Titre du chapitre|Titre de la leçon|Durée|Classe|Objectifs?|Évaluation|Remarques?|Sujet|Niveau|Matière|Pays)\s*:\s*(.*)$', line, flags=re.IGNORECASE)
            if m_lv:
                label = m_lv.group(1)
                value = m_lv.group(2)
                self.write_kv_pair(label, value)
                continue

            self.write_paragraph(line)

# =========================
# AI client + LLM utils
# =========================
def get_ai_client(api_provider: str, key_openrouter: str = "", key_gemini: str = ""):
    if "OpenRouter" in api_provider:
        # Streamlit Cloud: secrets first, then sidebar input, then env
        api_key = key_openrouter or _get_secret("OPENROUTER_API_KEY")
        if not api_key:
            st.error("OpenRouter API key missing. Add it in Options avancées or set OPENROUTER_API_KEY in secrets.")
            return None, None
        # Helpful headers for OpenRouter (avoid 401 and identify your app)
        referer = _get_secret("APP_PUBLIC_URL") or os.getenv("STREAMLIT_PUBLIC_URL", "")
        app_title = _get_secret("APP_NAME") or "FicheGen"
        default_headers = {k: v for k, v in {
            "HTTP-Referer": referer,
            "X-Title": app_title,
        }.items() if v}
        try:
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
                default_headers=default_headers or None,
            )
        except Exception as e:
            st.error(f"Échec initialisation OpenRouter: {e}")
            return None, None
        return client, "openrouter"
    elif "Gemini" in api_provider:
        api_key = key_gemini or _get_secret("GEMINI_API_KEY")
        if not api_key:
            st.error("Gemini API key missing. Add it in Options avancées or set GEMINI_API_KEY in secrets.")
            return None, None
        genai.configure(api_key=api_key)
        return genai.GenerativeModel(GEMINI_MODEL), "gemini"
    return None, None

def llm_call(client, client_type, prompt: str, model_name: str | None):
    try:
        if client_type == "openrouter":
            completion = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            return completion.choices[0].message.content
        elif client_type == "gemini":
            resp = client.generate_content(prompt)
            return resp.text
    except Exception as e:
        # Provide clearer guidance for common OpenRouter auth issues
        msg = str(e)
        if client_type == "openrouter" and ("401" in msg or "User not found" in msg):
            st.error("OpenRouter auth failed (401). Vérifiez votre OPENROUTER_API_KEY dans Secrets et, si nécessaire, définissez APP_PUBLIC_URL (URL publique de l'app) et APP_NAME.")
        else:
            st.error(f"AI API Error: {e}")
    return None

# =========================
# PDF extraction helpers
# =========================
def extract_table_of_contents(file_like, max_pages: int):
    """Extract text from the first N pages. Reset pointer first for safety."""
    try:
        file_like.seek(0)
    except Exception:
        pass
    toc_text = ""
    try:
        with pdfplumber.open(file_like) as pdf:
            num = min(max_pages, len(pdf.pages))
            for i in range(num):
                page = pdf.pages[i]
                text = page.extract_text()
                if text:
                    toc_text += text + "\n\n"
        return toc_text
    except Exception as e:
        st.error(f"PDF Extraction Error (ToC): {e}")
        return None

def extract_lesson_text(file_like, page_numbers):
    """Extract text for the specific pages returned by the page finder."""
    try:
        file_like.seek(0)
    except Exception:
        pass
    lesson_text = ""
    try:
        with pdfplumber.open(file_like) as pdf:
            for page_num in page_numbers:
                if 1 <= page_num <= len(pdf.pages):
                    page = pdf.pages[page_num - 1]
                    text = page.extract_text()
                    if text:
                        lesson_text += f"\n\n--- TEXT FROM PAGE {page_num} ---\n\n{text}"
                else:
                    st.warning(f"Page {page_num} out of bounds.")
        return lesson_text
    except Exception as e:
        st.error(f"PDF Extraction Error: {e}")
        return None

# =========================
# Prompts (your stronger versions)
# =========================
def get_pages_from_toc_prompt(toc_text, lesson_topic):
    return f"""
    You are an index analysis bot. Your task is to find the page numbers for a specific lesson topic from a book's table of contents.
    The lesson topic is: "{lesson_topic}"
    Here is the text of the table of contents:
    ---
    {toc_text}
    ---
    Analyze the table of contents and find the page or range of pages corresponding to the lesson topic.
    Respond with ONLY the page numbers.
    - If it's a single page, respond with the number (e.g., "42").
    - If it's a range of pages (which is most common), find the start page for "{lesson_topic}" and the start page for the *next* lesson, then subtract one. Respond with a dash (e.g., "42-46").
    Do NOT add any other words, sentences, or explanations. Just the numbers.
    """

def teacher_fiche_prompt(lesson_text, lesson_topic, class_level):
    fiche_structure = """
    ## Guide de conception d’une fiche pédagogique
    1. **Informations générales**
       - Titre du chapitre: (déduire du texte)
       - Titre de la leçon: (utiliser le sujet donné)
       - Durée: 45 min
       - Classe: (utiliser la classe donnée)
    2. **Objectifs**
       - Formuler 2-3 objectifs précis que l'élève doit savoir ou savoir-faire. Utiliser des verbes d'action (nommer, identifier, comparer…).
    3. **Déroulement de la séance** (utiliser des puces phrases; regrouper par phases avec durée, ex: "### Introduction (5 min)")
       - - phrase complète 1…
       - - phrase complète 2…
    4. **Évaluation**
       - Décrire les outils (questions orales, exercices écrits, etc.).
    5. **Remarques et conclusion**
       - Consignes simples, s'appuyer sur le manuel, encourager la participation.
    """
    example_fiche = """
    ## EXEMPLE DE STYLE
    Titre du chapitre : La santé de l'être humain.
    Titre de la leçon : Les 5 sens.
    Durée : 45 min.
    Classe : C.P.
    Objectif : Faire connaître aux élèves nos cinq principaux organes sensoriels...
    Déroulement: Pour commencer, je demande aux élèves de bien observer... je pose la question... je demande aux élèves de prendre leur livres page 8... Je passe vérifier les réponses. Je lis la consigne de l'exercice 2... Je demande aux élèves d'observer les images dans le manuel... Je distribue les fiches d'activités... Je passe vérifier les réponses... Pour conclure, je résume les points clés...
    (Le style est direct, utilise "je", et les actions sont concrètes.)
    Conclusion du cours (Le résumé bref de 2-4 lignes que les élèves doivent écrire dans leur cahiers à la fin de la leçon) : (Basée sur les objectifs de la leçon, en général, un résumé de ce que les élèves ont appris.)
    """
    return f"""Tu es un assistant expert pour les enseignants du primaire au Maroc. Ta tâche est de créer une "Fiche Pédagogique" claire, engageante et structurée en français.

**MISSION:**
Crée une fiche pédagogique complète pour la leçon "{lesson_topic}" pour la classe de {class_level}.

**MATÉRIEL SOURCE (Texte du manuel scolaire sur lequel tu dois te baser, car suivre le programme pédagogique est essentiel, mais aussi créer une atmosphère d'éducation, qui respecte l'enchaînement de la leçon et le rythme auquel les élèves peuvent se sentir confortables et pas accablés):**
---
{lesson_text}
---

**STRUCTURE REQUISE (à remplir):**
---
{fiche_structure}
---

**EXEMPLE DE STYLE À IMITER (Ceci est un excellent exemple que tu dois imiter, le professeur ici commence par interagire avec les élèves):**
---
{example_fiche}
---

**INSTRUCTIONS DÉTAILLÉES:**
1. Analyse le MATÉRIEL SOURCE pour comprendre les concepts clés de la leçon.
2. Remplis chaque section de la STRUCTURE REQUISE en te basant sur le matériel.
3. Adopte le ton et le style de l'EXEMPLE: direct, pratique, et utilisant "je" pour décrire les actions de l'enseignant.
4. Sois créatif mais fidèle: activités engageantes, mais conformes au manuel.
5. Formatage Markdown: sous-titres de phase au format `### Titre de phase (X min)` puis des puces phrases complètes.
6. Reste faisable en 45 min pour le déroulement, realistiquement, ca entaille 30 minutes de class, et le rest est vide, ne notte pas ces moments vide, mais reste conscient d'eux, on a besoin d'un rhythme et avencement realiste dans la classe.
7. Commence directement, sans phrases d'introduction.
8. Utilise des transitions claires entre les activités pour maintenir l'attention des élèves.
9. Réfère-toi aux activités/exercices dans le manuel. (e.x. Je demande aux élèves de prendre leur livre page X… EX Y... Je lis la consigne de l'exercice Y... Je demande aux élèves d'observer les images dans le manuel... etc)
"""

def student_notes_prompt(lesson_text, topic, class_level):
    return f"""
Crée une fiche de révision claire en français.

SUJET: {topic}
NIVEAU: {class_level}

TEXTE SOURCE:
---
{lesson_text}
---

FORMAT MARKDOWN:
## Sujet Principal
Titre: {topic}
Niveau: {class_level}

## Les Idées Clés
- Puces simples. Mets en gras les termes clés.

## Définitions Importantes
- **Terme**: Définition simple.

## Exemples Pratiques
- 1–2 exemples.

## Résumé en une Phrase
- Une seule phrase qui résume tout.

IMPORTANT: Commence directement sans phrases d'intro.
"""

def student_notes_no_syllabus_prompt(topic, class_level, country, subject):
    return f"""
Crée une fiche de révision en français pour un élève.

CONTEXTE:
- Matière: {subject}
- Niveau: {class_level}
- Pays/Curriculum: {country}

FORMAT MARKDOWN:
## Sujet Principal
Titre: {topic}
Matière: {subject}
Niveau: {class_level}
Pays: {country}

## Les Idées Clés
- Puces simples. Mets en gras les **termes clés**.

## Définitions Importantes
- **Terme**: Définition simple.

## Exemples Pratiques
- 1–2 exemples.

## Pour Aller Plus Loin (Optionnel)
- Suggestion liée ou fun fact.

IMPORTANT: Commence directement.
"""

def parse_page_numbers(page_str: str):
    pages = []
    cleaned = ''.join(re.findall(r'[\d,-]', page_str or ""))
    if not cleaned:
        return []
    try:
        for part in cleaned.split(','):
            part = part.strip()
            if not part:
                continue
            if '-' in part:
                a, b = map(int, part.split('-'))
                pages.extend(range(a, b + 1))
            else:
                pages.append(int(part))
        return sorted(set(pages))
    except Exception:
        return []

# =========================
# UI
# =========================
st.set_page_config(page_title="Générateur de Fiches", layout="wide")
st.title("Générateur de Fiches Automatisé 🚀")
st.write("Crée des fiches pédagogiques (enseignants) et des fiches de révision (étudiants).")

# Sidebar: clean basics up front
with st.sidebar:
    st.header("Configuration")

    # Role
    user_type = option_menu(
        "Qui êtes-vous?",
        ["👨‍🏫 Enseignant", "🧑‍🎓 Étudiant"],
        icons=['easel', 'book'],
        menu_icon="cast",
        default_index=0
    )
    role = "teacher" if "Enseignant" in user_type else "student"

    # Base style selector (visible)
    st.selectbox(
        "Style PDF",
        ["teal", "pro", "study"],
        index=0,
        format_func=lambda x: {"teal": "Classique (Teal + Gutter)", "pro": "Professionnel", "study": "Moderne"}[x],
        key="pdf_base_template"
    )

    # Provider selector (visible). Model+keys inside advanced.
    st.selectbox("Fournisseur IA", ["OpenRouter", "Gemini"], index=0, key="api_provider")

    # Advanced options tucked away
    with st.expander("Options avancées", expanded=False):
        # Single shared model selector
        if st.session_state.get("api_provider") == "OpenRouter":
            st.selectbox("Modèle OpenRouter", OPENROUTER_MODELS, index=0, key="openrouter_model")
        else:
            st.info(f"Modèle Gemini utilisé: {GEMINI_MODEL}")

        st.subheader("Clés API")
        key_or = st.text_input("OpenRouter API Key", type="password", help="Collez votre clé OpenRouter si utilisé")
        key_g = st.text_input("Gemini API Key", type="password", help="Collez votre clé Gemini si utilisé")
        if key_or:
            st.session_state["openrouter_key"] = key_or
        if key_g:
            st.session_state["gemini_key"] = key_g

        st.markdown("---")
        st.subheader("PDF - Paramètres avancés + Modèles")

        colA, colB, colC = st.columns(3)
        with colA:
            st.selectbox("Taille de page", ["A4", "Letter"], index=0, key="pdf_page_format")
        with colB:
            st.selectbox("Orientation", ["P", "L"], index=0, key="pdf_orientation", format_func=lambda x: "Portrait" if x == "P" else "Paysage")
        with colC:
            st.number_input("Pages à scanner (ToC)", 1, 12, TABLE_OF_CONTENTS_PAGES_DEFAULT, key="toc_pages")

        colM1, colM2, colM3 = st.columns(3)
        with colM1:
            st.number_input("Marge gauche", 5, 50, 15, key="pdf_margin_left")
        with colM2:
            st.number_input("Marge droite", 5, 50, 15, key="pdf_margin_right")
        with colM3:
            st.number_input("Marge haut", 5, 50, 20, key="pdf_margin_top")

        colT1, colT2 = st.columns(2)
        with colT1:
            st.slider("Taille de police", 9, 16, 12, key="pdf_font_size")
        with colT2:
            st.slider("Interligne", 0.9, 1.6, 1.15, 0.05, key="pdf_line_spacing")

        st.checkbox("Page de couverture", key="pdf_show_cover")
        st.text_input("Filigrane (optionnel)", key="pdf_watermark", placeholder="Créé avec FicheGen")

        # Save/load template configs as JSON
        TEMPLATES_DIR = "templates"
        os.makedirs(TEMPLATES_DIR, exist_ok=True)

        def current_pdf_cfg():
            return {
                "base_template": st.session_state.get("pdf_base_template", "teal"),
                "page_format": st.session_state.get("pdf_page_format", "A4"),
                "orientation": st.session_state.get("pdf_orientation", "P"),
                "margins": (
                    st.session_state.get("pdf_margin_left", 15),
                    st.session_state.get("pdf_margin_right", 15),
                    st.session_state.get("pdf_margin_top", 20),
                ),
                "base_font_size": st.session_state.get("pdf_font_size", 12),
                "line_spacing": st.session_state.get("pdf_line_spacing", 1.15),
                "show_cover": st.session_state.get("pdf_show_cover", False),
                "watermark_text": st.session_state.get("pdf_watermark", "").strip(),
            }

        def apply_pdf_cfg(cfg):
            st.session_state["pdf_base_template"] = cfg.get("base_template", "teal")
            st.session_state["pdf_page_format"] = cfg.get("page_format", "A4")
            st.session_state["pdf_orientation"] = cfg.get("orientation", "P")
            m = cfg.get("margins", (15, 15, 20))
            st.session_state["pdf_margin_left"] = m[0]
            st.session_state["pdf_margin_right"] = m[1]
            st.session_state["pdf_margin_top"] = m[2]
            st.session_state["pdf_font_size"] = cfg.get("base_font_size", 12)
            st.session_state["pdf_line_spacing"] = cfg.get("line_spacing", 1.15)
            st.session_state["pdf_show_cover"] = cfg.get("show_cover", False)
            st.session_state["pdf_watermark"] = cfg.get("watermark_text", "")

        colS1, colS2 = st.columns([2, 1])
        with colS1:
            tpl_name = st.text_input("Nom du modèle PDF", placeholder="Mon style préféré")
        with colS2:
            if st.button("Enregistrer modèle"):
                safe = "".join(ch for ch in (tpl_name or "") if ch.isalnum() or ch in " _-").strip()
                if not safe:
                    st.error("Nom invalide.")
                else:
                    path = os.path.join(TEMPLATES_DIR, f"{safe}.json")
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(current_pdf_cfg(), f, ensure_ascii=False, indent=2)
                    st.success(f"Modèle enregistré: {path}")

        files = sorted([f for f in os.listdir(TEMPLATES_DIR) if f.endswith(".json")])
        if files:
            colL1, colL2, colL3 = st.columns([2, 1, 1])
            with colL1:
                chosen = st.selectbox("Charger un modèle", files, index=0)
            with colL2:
                if st.button("Charger"):
                    try:
                        with open(os.path.join(TEMPLATES_DIR, chosen), "r", encoding="utf-8") as f:
                            cfg = json.load(f)
                        apply_pdf_cfg(cfg)
                        st.success("Modèle appliqué.")
                    except Exception as e:
                        st.error(f"Erreur de chargement: {e}")
            with colL3:
                if st.button("Supprimer"):
                    try:
                        os.remove(os.path.join(TEMPLATES_DIR, chosen))
                        st.success("Supprimé. Repliez/réouvrez l'expander pour rafraîchir.")
                    except Exception as e:
                        st.error(f"Erreur suppression: {e}")

# Helper to build and offer the PDF
def build_pdf_and_download(edited_text, filename_base, role):
    cover_meta = {
        "title": filename_base.replace("_", " "),
        "class_level": "",
        "duration": "45 min",
        "author": "",
        "date": datetime.date.today().strftime("%Y-%m-%d"),
    }
    pdf = PDF(
        doc_type=role,
        base_template=st.session_state.get("pdf_base_template", "teal"),
        page_format=st.session_state.get("pdf_page_format", "A4"),
        orientation=st.session_state.get("pdf_orientation", "P"),
        margins=(
            st.session_state.get("pdf_margin_left", 15),
            st.session_state.get("pdf_margin_right", 15),
            st.session_state.get("pdf_margin_top", 20),
        ),
        base_font_size=st.session_state.get("pdf_font_size", 12),
        line_spacing=st.session_state.get("pdf_line_spacing", 1.15),
        show_cover=st.session_state.get("pdf_show_cover", False),
        cover_meta=cover_meta,
        watermark_text=st.session_state.get("pdf_watermark", "").strip()
    )
    pdf.add_content(edited_text)
    pdf_bytes = bytes(pdf.output(dest='S'))
    st.download_button("⬇️ Télécharger le PDF", data=pdf_bytes, file_name=f"{filename_base}.pdf", mime="application/pdf")

# =========================
# Tabs
# =========================
tab1, tab2 = st.tabs(["📘 Depuis un Syllabus (PDF)", "✍️ Sujet Libre"])

# --- TAB 1: From Syllabus with reactive progress ---
with tab1:
    st.header("Génération depuis un Syllabus PDF")
    uploaded = st.file_uploader("📄 Choisir le PDF (manuel / syllabus)", type="pdf")
    c1, c2 = st.columns(2)
    with c1:
        lesson_topic = st.text_input("Sujet de la leçon", placeholder="Ex: Les 5 sens")
    with c2:
        class_level = st.text_input("Niveau/Classe", placeholder="Ex: CP, 6ème")

    gen_clicked = st.button("✨ Générer depuis le Syllabus", disabled=not (uploaded and lesson_topic and class_level))

    if gen_clicked:
        # Progress UI elements up-front so user sees immediate feedback
        progress_container = st.container()
        progress_bar = progress_container.progress(0)
        status_text = progress_container.empty()

        try:
            # 1) Init client
            status_text.text("🔧 Initialisation du client IA...")
            progress_bar.progress(10)
            client, client_type = get_ai_client(
                st.session_state.get("api_provider", "OpenRouter"),
                key_openrouter=st.session_state.get("openrouter_key", ""),
                key_gemini=st.session_state.get("gemini_key", "")
            )
            if not client:
                st.stop()

            # 2) Extract ToC
            status_text.text("📖 Extraction de la table des matières...")
            progress_bar.progress(25)
            toc_pages = st.session_state.get("toc_pages", TABLE_OF_CONTENTS_PAGES_DEFAULT)
            toc_text = extract_table_of_contents(uploaded, toc_pages)
            if not toc_text:
                st.error("Impossible d'extraire la table des matières.")
                st.stop()

            # 3) Find pages
            status_text.text(f"🧠 Recherche des pages pour « {lesson_topic} »...")
            progress_bar.progress(50)
            prompt_pages = get_pages_from_toc_prompt(toc_text, lesson_topic)
            model_to_use = st.session_state.get("openrouter_model", OPENROUTER_MODELS[0]) if client_type == "openrouter" else None
            pages_str = llm_call(client, client_type, prompt_pages, model_to_use)
            if not pages_str:
                st.error("Impossible d'obtenir les numéros de pages.")
                st.stop()

            pages = parse_page_numbers(pages_str)
            if not pages:
                st.error(f"Pages introuvables pour « {lesson_topic} ». Réessaie ou ajuste le sujet.")
                st.stop()

            # 4) Extract lesson content
            status_text.text(f"📄 Extraction du contenu (pages {pages_str})...")
            progress_bar.progress(75)
            lesson_text = extract_lesson_text(uploaded, pages)
            if not lesson_text:
                st.error("Impossible d'extraire le texte de la leçon.")
                st.stop()

            # 5) Generate content
            status_text.text("🤖 Génération de la fiche (cela peut prendre un moment)...")
            progress_bar.progress(90)
            if role == "teacher":
                prompt = teacher_fiche_prompt(lesson_text, lesson_topic, class_level)
            else:
                prompt = student_notes_prompt(lesson_text, lesson_topic, class_level)

            generated = llm_call(client, client_type, prompt, model_to_use)
            if not generated:
                st.error("Échec de génération.")
                st.stop()

            # 6) Done
            progress_bar.progress(100)
            status_text.text("✅ Génération terminée!")
            st.session_state.generated_content = generated
            st.session_state.doc_type = role
            st.session_state.file_base = f"Fiche_{lesson_topic.replace(' ', '_')}_{class_level}"

            # Let the user enjoy the 100% moment
            time.sleep(0.8)
            progress_container.empty()

            st.success("🎉 Contenu généré avec succès!")

        except Exception as e:
            progress_container.empty()
            st.error(f"Erreur durant la génération: {e}")

# --- TAB 2: Free topic with reactive progress ---
with tab2:
    st.header("Génération libre (sans syllabus)")
    c1, c2 = st.columns(2)
    with c1:
        free_topic = st.text_input("Sujet", placeholder="Ex: La photosynthèse", key="free_topic")
        subject = st.text_input("Matière", placeholder="Ex: Biologie", key="subject")
    with c2:
        free_class_level = st.text_input("Niveau/Classe", placeholder="Ex: 4ème", key="free_level")
        country = st.text_input("Pays/Curriculum", placeholder="Ex: Maroc / France", key="country")

    gen_free = st.button("✨ Générer Fiche Libre", disabled=not all([free_topic, subject, free_class_level, country]))

    if gen_free:
        progress_container2 = st.container()
        progress_bar2 = progress_container2.progress(0)
        status_text2 = progress_container2.empty()

        try:
            # 1) Init client
            status_text2.text("🔧 Initialisation du client IA...")
            progress_bar2.progress(15)
            client, client_type = get_ai_client(
                st.session_state.get("api_provider", "OpenRouter"),
                key_openrouter=st.session_state.get("openrouter_key", ""),
                key_gemini=st.session_state.get("gemini_key", "")
            )
            if not client:
                st.stop()

            # 2) Generate content
            status_text2.text("🤖 Génération de la fiche...")
            progress_bar2.progress(70)
            model_to_use = st.session_state.get("openrouter_model", OPENROUTER_MODELS[0]) if client_type == "openrouter" else None
            # Free-topic path: use student notes prompt by default
            prompt = student_notes_no_syllabus_prompt(free_topic, free_class_level, country, subject)
            generated = llm_call(client, client_type, prompt, model_to_use)
            if not generated:
                st.error("Échec de génération.")
                st.stop()

            # 3) Done
            progress_bar2.progress(100)
            status_text2.text("✅ Génération terminée!")
            st.session_state.generated_content = generated
            st.session_state.doc_type = "student"
            st.session_state.file_base = f"Fiche_{free_topic.replace(' ', '_')}"

            time.sleep(0.8)
            progress_container2.empty()
            st.success("🎉 Contenu généré avec succès!")

        except Exception as e:
            progress_container2.empty()
            st.error(f"Erreur durant la génération: {e}")

# =========================
# Preview + Download
# =========================
if 'generated_content' in st.session_state:
    st.markdown("---")
    st.header("📝 Aperçu modifiable")
    edited = st.text_area(
        "Contenu (Markdown)",
        value=st.session_state.get("edited_content", st.session_state.generated_content),
        height=360
    )
    st.session_state.edited_content = edited
    st.subheader("📥 Export")
    build_pdf_and_download(edited, st.session_state.get("file_base", "Fiche"), st.session_state.get("doc_type", "student"))
