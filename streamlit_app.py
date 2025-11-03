import os
import json
import time
import base64
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# --- Google AI Studio (Gemini) ---
import google.generativeai as genai

# ---------- Config ----------
APP_TITLE = "Contador de Histórias"
DEFAULT_TONE = "Aleatório"  # [Aleatório, Aventura, Engraçada, Calma, Misteriosa]
DEFAULT_DURATION = "~4 min"  # [~2 min, ~4 min, ~6 min]

# Layout constants
BG_HEX = "#020617"       # fundo
CARD_HEX = "#111827"     # cards
BTN_HEX = "#4F46E5"      # botões (indigo-600)
TEXT_HEX = "#e5e7eb"     # slate-200/300
MORAL_HEX = "#818cf8"    # indigo-400

# ---------- Helpers ----------
def read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()

def load_prompts():
    base = Path(__file__).parent / "prompts"
    return {
        "storyteller": read_text(base / "storyteller_prompt.txt"),
        "guardrails": read_text(base / "guardrails_prompt.txt"),
        "imgsum": read_text(base / "image_summarizer_prompt.txt"),
    }

def configure_gemini():
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        st.error("Faltou configurar GOOGLE_API_KEY no .env / Secrets do Streamlit.")
        st.stop()
    genai.configure(api_key=api_key)

# UI CSS to match screenshots
def inject_css():
    st.markdown(f"""
    <style>
      .stApp {{ background-color: {BG_HEX}; }}
      .block-container {{ padding-top: 2rem; padding-bottom: 4rem; max-width: 512px; }}
      h1, h2, h3, h4, h5, h6 {{ color: white; }}
      .card {{
        background: {CARD_HEX};
        border-radius: 16px;
        padding: 16px 16px 8px 16px;
        border: 1px solid rgba(255,255,255,0.05);
      }}
      .story-title {{ font-size: 1.25rem; font-weight: 700; color: #fff; margin-bottom: .5rem; }}
      .story-text {{ color: #cbd5e1; line-height: 1.7; }}
      .story-moral {{ color: {MORAL_HEX}; font-weight: 600; margin-top: .75rem; }}
      .stButton>button {{
        background: {BTN_HEX}; color: white; border: none; border-radius: 12px;
        padding: .8rem 1rem; font-weight: 600;
      }}
      .stButton>button:disabled {{
        background: #475569 !important; color: #cbd5e1 !important;
      }}
      .muted {{ color: #94a3b8; font-size: .85rem; }}
      label, .stCheckbox, .stSelectbox label, .stTextInput label {{ color: #94a3b8 !important; }}
      .stTextInput>div>div>input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] input {{
        background: #0f172a; color: #e5e7eb;
      }}
    </style>
    """, unsafe_allow_html=True)

# ---------- AI calls ----------
def validate_user_idea(idea: str, prompts: dict) -> dict:
    """
    Returns dict like:
      {"decision": "USE_AS_IS" | "SANITIZE" | "IGNORE", "notes": "..."}
    Any non-USE_AS_IS will be treated as IGNORE (no personalization).
    """
    if not idea.strip():
        return {"decision": "USE_AS_IS", "notes": "Empty -> proceed with defaults (no personalization provided)."}

    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=prompts["guardrails"]
    )
    resp = model.generate_content(idea)
    text = resp.text or "{}"
    try:
        data = json.loads(text)
        # normalize
        decision = str(data.get("decision", "")).upper().strip()
        if decision not in {"USE_AS_IS", "SANITIZE", "IGNORE"}:
            decision = "IGNORE"
        return {"decision": decision, "notes": data.get("notes", "")}
    except Exception:
        # If parser fails, be conservative
        return {"decision": "IGNORE", "notes": "Unparseable guardrails response"}

def build_user_prompt(idea: str, tone: str, duration: str) -> str:
    # Map duration to target words
    target = {"~2 min": 320, "~4 min": 460, "~6 min": 700}.get(duration, 460)
    tone_pt = tone if tone != "Aleatório" else "aleatório (deixe o modelo escolher entre aventura, engraçada, calma ou misteriosa)"
    lines = [
        f"Ideia principal do usuário: {idea.strip() or '(não especificada; crie uma história original e positiva)'}",
        f"Tom: {tone_pt}.",
        f"Duração alvo: cerca de {target} palavras.",
        "Formato: título, parágrafos curtos, moral destacada no final.",
    ]
    return "\n".join(lines)

def generate_story(user_prompt: str, prompts: dict) -> str:
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=prompts["storyteller"]
    )
    resp = model.generate_content(user_prompt)
    return resp.text

def summarize_for_image_prompt(story_text: str, prompts: dict) -> str:
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=prompts["imgsum"]
    )
    resp = model.generate_content(story_text)
    return (resp.text or "").strip()

def generate_story_image(img_prompt_en: str) -> bytes:
    """
    Uses Imagen 3.0 to generate a PNG from a short English prompt.
    Returns raw PNG bytes.
    """
    # Some SDKs expose this via genai.ImageGenerationModel; here we use the generic client
    # If your installed SDK version differs, check README for alternatives.
    image_model = genai.GenerativeModel("imagen-3.0-generate-001")
    img = image_model.generate_content(img_prompt_en, generation_config={"response_mime_type": "image/png"})
    # SDK returns a blob-like part; handle typical patterns:
    if hasattr(img, "binary") and img.binary:
        return img.binary
    # Fallback: find first image in parts
    for p in getattr(img, "parts", []):
        if getattr(p, "mime_type", "") == "image/png" and getattr(p, "data", None):
            return p.data
    raise RuntimeError("Imagem não retornada pela API.")

# ---------- Streamlit App ----------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="📖", layout="centered")
    inject_css()
    st.markdown(f"<h1 style='text-align:center'>{APP_TITLE}</h1>", unsafe_allow_html=True)

    configure_gemini()
    prompts = load_prompts()

    # Card de Personalização (inicia colapsado)
    with st.container():
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        expand = st.toggle("Personalizar", value=False)
        idea = ""
        tone = DEFAULT_TONE
        duration = DEFAULT_DURATION
        gen_image = True

        if expand:
            idea = st.text_input("Ideia principal (opcional)", placeholder="ex.: 'um coelho que quer voar'")
            tone = st.selectbox("Tom", ["Aleatório", "Aventura", "Engraçada", "Calma", "Misteriosa"], index=0)
            duration = st.selectbox("Duração", ["~2 min", "~4 min", "~6 min"], index=1)
            gen_image = st.checkbox("Gerar Ilustração", value=True)
        else:
            gen_image = True  # habilitado por padrão

        col = st.columns([1])[0]
        generate = st.button("Gerar História", use_container_width=True, type="primary")

        st.markdown("</div>", unsafe_allow_html=True)

    # Área de resultado
    placeholder_story = st.empty()
    placeholder_image = st.empty()

    if generate:
        with st.spinner("Gerando..."):
            # 1) Guardrails
            guard = validate_user_idea(idea, prompts)
            if guard["decision"] != "USE_AS_IS":
                effective_idea = ""  # descarta personalização para máxima segurança
            else:
                effective_idea = idea

            # 2) Build prompt & gerar história
            user_prompt = build_user_prompt(effective_idea, tone, duration)
            story = generate_story(user_prompt, prompts)

            # Render história
            if story:
                # título (primeira linha até quebra dupla) – fallback simples
                placeholder_story.markdown(
                    f"""
                    <div class='card'>
                      <div class='story-title'>{" ".join(story.splitlines()[0:1])}</div>
                      <div class='story-text'>{"<br/>".join(story.splitlines()[1:])}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            else:
                placeholder_story.error("Não foi possível gerar a história.")

            # 3) Imagem (opcional)
            if gen_image and story:
                try:
                    img_prompt = summarize_for_image_prompt(story, prompts)
                    png_bytes = generate_story_image(img_prompt)
                    placeholder_image.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
                    placeholder_image.image(png_bytes, caption=None, use_column_width=True)
                except Exception as e:
                    placeholder_image.warning(f"Ilustração desativada ou não disponível: {e}")

            st.toast("Concluído", icon="✅")

if __name__ == "__main__":
    main()
