## FicheGen — Générateur de fiches pédagogiques et de révision

FicheGen est une application Streamlit qui génère des fiches pédagogiques (enseignants) et des fiches de révision (élèves) à partir d’un PDF (syllabus/manuel) ou d’un sujet libre. Le contenu est produit via des modèles IA (OpenRouter ou Gemini), puis exportable en PDF avec un rendu propre et configurable.

### Fonctionnalités
- Deux modes de génération:
	- Depuis un PDF: retrouve automatiquement les pages du sujet dans la table des matières, extrait le texte, puis génère la fiche.
	- Sujet libre: génère directement une fiche structurée sans PDF.
- Choix du fournisseur IA: OpenRouter (modèles variés) ou Google Gemini.
- PDF soigné avec gabarits « teal », « pro » ou « study », marges, police, interligne, orientation, filigrane, page de couverture, etc.
- Sauvegarde et rechargement de modèles de configuration PDF (dossier `templates/`).
- Téléchargement du PDF final en un clic.

## Prérequis
- Python 3.10+ recommandé
- Compte et clé API pour l’un des fournisseurs IA:
	- OpenRouter: https://openrouter.ai/
	- Google Gemini: https://ai.google.dev/

## Installation
1) Cloner le dépôt et se placer dans le dossier
```bash
git clone <this-repo-url>
cd FicheGen
```

2) Créer un environnement virtuel (optionnel mais conseillé)
```bash
python -m venv .venv
source .venv/bin/activate
```

3) Installer les dépendances
```bash
pip install -r requirements.txt
```

4) (Optionnel) Polices DejaVu pour un rendu PDF unicode complet
- Placez `DejaVuSans.ttf` et `DejaVuSans-Bold.ttf` à la racine du projet (même dossier que `app.py`).
- Sans ces fichiers, l’app utilisera Arial avec un support unicode limité.

## Configuration des clés API
Vous pouvez saisir vos clés dans l’interface (Options avancées), ou les définir via des variables d’environnement/`.env`.

Fichier `.env` (à créer à la racine):
```env
# Utilisez l’un ou l’autre (ou les deux)
OPENROUTER_API_KEY=sk-or-...
GEMINI_API_KEY=AIza...
```
L’application charge automatiquement `.env` grâce à `python-dotenv`.

## Lancer l’application
```bash
streamlit run app.py
```
Streamlit ouvrira automatiquement l’interface dans votre navigateur (sinon, copiez l’URL affichée dans le terminal).

## Utilisation
### 1) Onglet « Depuis un Syllabus (PDF) »
1. Téléversez le PDF (manuel/syllabus).  
2. Renseignez « Sujet de la leçon » et « Niveau/Classe ».  
3. Cliquez « Générer depuis le Syllabus ».

Ce qui se passe:
- L’app lit N pages de la table des matières (paramètre « Pages à scanner (ToC) »).  
- L’IA détecte les pages correspondant au sujet (ex.: « 42-46 »).  
- Le texte de ces pages est extrait et passé à un prompt spécialisé.  
- Une fiche est générée (style enseignant ou étudiant suivant votre rôle) et affichée en aperçu.

### 2) Onglet « Sujet Libre »
1. Indiquez Sujet, Matière, Niveau/Classe et Pays/Curriculum.  
2. Cliquez « Générer Fiche Libre » pour produire une fiche de révision structurée.

### Options avancées (barre latérale)
- Fournisseur IA: OpenRouter ou Gemini.  
	- OpenRouter: choisissez un modèle (ex.: `deepseek/deepseek-chat-v3.1:free`, `mistralai/mistral-small-3.2-24b-instruct`, etc.).
	- Gemini: le modèle utilisé est `gemini-2.5-flash`.
- PDF: gabarit, format (A4/Letter), orientation (Portrait/Paysage), marges, police, interligne, page de couverture, filigrane.  
- Modèles PDF: enregistrez/chargez/supprimez des configurations dans `templates/`.

### Aperçu et export
Après génération, vous pouvez modifier le texte Markdown dans l’aperçu puis exporter en PDF via le bouton « Télécharger le PDF ».

## Structure du projet
```
app.py               # Application Streamlit
requirements.txt     # Dépendances Python
README.md            # Ce guide
templates/           # (créé au besoin) configurations PDF sauvegardées
```

## Conseils et dépannage
- Extraction PDF vide: si le PDF est scanné (images), `pdfplumber` peut ne pas extraire de texte.  
	- Solution: utilisez une version texte, ou appliquez un OCR (ex.: Tesseract) avant d’importer.
- Clés API: assurez-vous de saisir la clé correspondant au fournisseur sélectionné (OpenRouter ou Gemini).  
- DejaVu fonts: placez `DejaVuSans.ttf` et `DejaVuSans-Bold.ttf` à la racine pour un meilleur support unicode.  
- Pages trouvées incorrectes: affinez le libellé du « Sujet de la leçon » ou augmentez « Pages à scanner (ToC) ».
- Limites modèles « free »: les files gratuites peuvent être lentes ou instables; essayez un autre modèle si nécessaire.

## Sécurité & confidentialité
- Les clés API ne sont jamais envoyées à un service tiers autre que le fournisseur IA choisi.  
- L’extraction PDF se fait localement; seul le texte utile est envoyé au modèle IA.

## Licence
Spécifiez votre licence ici (ex.: MIT). Si vous ne savez pas encore, laissez ce champ et ajoutez un fichier LICENSE plus tard.

## Remerciements
- Streamlit, pdfplumber, fpdf2, OpenAI SDK, Google Generative AI, et la communauté open-source.
