import os
import json
import base64
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai

# ---------- Versão ----------
VERSION = "v1.1.0 (2025-11-03)"

# ---------- Config ----------
APP_TITLE = "Contador de Histórias"

DEFAULT_TONE = "Aleatório"   # [Aleatório, Aventura, Engraçada, Calma, Misteriosa]
DEFAULT_DURATION = "~4 min"  # [~2 min, ~4 min, ~6 min]

# Layout / Cores
BG_HEX = "#020617"       # fundo
CARD_HEX = "#111827"     # cards
BTN_HEX = "#4F46E5"      # botões (indigo-600)
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
      code {{ color:#e5e7eb; }}
    </style>
    """, unsafe_allow_html=True)

# ---------- AI calls ----------
def validate_user_idea(idea: str, prompts: dict) -> dict:
    """Guardrails via LLM -> retorna decisão JSON. SANITIZE/IGNORE => não personaliza."""
    if not idea.strip():
        return {"decision": "USE_AS_IS", "notes": "Sem personalização informada."}
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=prompts["guardrails"]
    )
    resp = model.generate_content(idea)
    text = resp.text or "{}"
    try:
        data = json.loads(text)
        decision = str(data.get("decision", "")).upper().strip()
        if decision not in {"USE_AS_IS", "SANITIZE", "IGNORE"}:
            decision = "IGNORE"
        return {"decision": decision, "notes": data.get("notes", "")}
    except Exception:
        return {"decision": "IGNORE", "notes": "Resposta do guardrails não parseável."}

def build_user_prompt(idea: str, tone: str, duration: str) -> str:
    target = {"~2 min": 320, "~4 min": 460, "~6 min": 700}.get(duration, 460)
    tone_pt = tone if tone != "Aleatório" else \
        "aleatório (deixe o modelo escolher: aventura, engraçada, calma ou misteriosa)"
    lines = [
        f"Ideia principal do usuário: {idea.strip() or '(não especificada; crie uma história original e positiva)'}",
        f"Tom: {tone_pt}.",
        f"Duração alvo: cerca de {target} palavras.",
        "Formato: título, parágrafos curtos, moral destacada ao final.",
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
    Gera PNG usando o modelo de imagem: 'models/gemini-2.5-flash-image'.
    """
    image_model = genai.GenerativeModel("models/gemini-2.5-flash-image")
    resp = image_model.generate_content(
        img_prompt_en,
        generation_config={"response_mime_type": "image/png"}
    )
    if hasattr(resp, "binary") and resp.binary:
        return resp.binary
    for p in getattr(resp, "parts", []):
        if getattr(p, "mime_type", "") == "image/png" and getattr(p, "data", None):
            return p.data
        if isinstance(getattr(p, "text", None), str) and p.text.startswith("data:image/png;base64,"):
            return base64.b64decode(p.text.split(",", 1)[1])
    raise RuntimeError("Imagem não retornada pelo modelo de imagem.")

# ---------- Cancelamento cooperativo ----------
def _maybe_stop():
    if st.session_state.get("stop"):
        st.session_state["busy"] = False
        st.session_state["stop"] = False
        st.toast("Geração interrompida.", icon="🛑")
        st.stop()

# ---------- App ----------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="📖", layout="centered")
    inject_css()
    st.markdown(f"<h1 style='text-align:center'>{APP_TITLE}</h1>", unsafe_allow_html=True)
    st.markdown(f"<div class='muted' style='text-align:center;margin-top:-6px;'>Versão {VERSION}</div>", unsafe_allow_html=True)

    # Estado
    if "busy" not in st.session_state: st.session_state["busy"] = False
    if "confirm_stop" not in st.session_state: st.session_state["confirm_stop"] = False
    if "stop" not in st.session_state: st.session_state["stop"] = False

    configure_gemini()
    prompts = load_prompts()

    # --- Card de Personalização (colapsado por padrão) ---
    with st.container():
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        expand = st.toggle("Personalizar", value=False, disabled=st.session_state["busy"])

        idea = ""
        tone = DEFAULT_TONE
        duration = DEFAULT_DURATION
        gen_image = True

        if expand:
            idea = st.text_input(
                "Ideia principal (opcional)",
                placeholder="ex.: 'um coelho que quer voar'",
                disabled=st.session_state["busy"]
            )
            tone = st.selectbox(
                "Tom", ["Aleatório", "Aventura", "Engraçada", "Calma", "Misteriosa"],
                index=0, disabled=st.session_state["busy"]
            )
            duration = st.selectbox(
                "Duração", ["~2 min", "~4 min", "~6 min"],
                index=1, disabled=st.session_state["busy"]
            )
            gen_image = st.checkbox("Gerar Ilustração", value=True, disabled=st.session_state["busy"])
        else:
            gen_image = True  # habilitado por padrão

        # Botão principal / Interromper
        if not st.session_state["busy"]:
            clicked = st.button("Gerar História", use_container_width=True, type="primary")
        else:
            clicked = False
            stop_clicked = st.button("Interromper geração", use_container_width=True)
            if stop_clicked:
                st.session_state["confirm_stop"] = True

        st.markdown("</div>", unsafe_allow_html=True)

    # Modal de confirmação para interromper
    if st.session_state["confirm_stop"]:
        st.warning("Interromper a geração? Esta ação cancela o processo atual.")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Sim, interromper agora", use_container_width=True):
                st.session_state["stop"] = True
                st.session_state["confirm_stop"] = False
        with col2:
            if st.button("Não, continuar", use_container_width=True):
                st.session_state["confirm_stop"] = False

    # Área de resultado
    placeholder_story = st.empty()
    placeholder_image = st.empty()

    # --- Fluxo de geração ---
    if clicked:
        st.session_state["busy"] = True
        st.session_state["stop"] = False
        with st.spinner("Gerando..."):
            _maybe_stop()
            guard = validate_user_idea(idea, prompts)
            _maybe_stop()
            effective_idea = "" if guard["decision"] != "USE_AS_IS" else idea

            user_prompt = build_user_prompt(effective_idea, tone, duration)
            story = generate_story(user_prompt, prompts)
            _maybe_stop()

            if story:
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
                st.session_state["busy"] = False
                st.stop()

            if gen_image and story:
                try:
                    img_prompt = summarize_for_image_prompt(story, prompts)
                    _maybe_stop()
                    png_bytes = generate_story_image(img_prompt)
                    _maybe_stop()
                    placeholder_image.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
                    placeholder_image.image(png_bytes, use_column_width=True)
                except Exception as e:
                    placeholder_image.warning(f"Ilustração desativada ou não disponível: {e}")

        st.session_state["busy"] = False
        st.toast("Concluído", icon="✅")

    # --- Rodapé “pague um café” + versão ---
    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
    with st.container():
        st.markdown(f"""
        <div class='card'>
          <div class='story-text'>
            <b>Curtiu o app?</b> Se este projeto te ajudou, considere pagar um café ☕.<br/>
            <span class='muted'>PIX (chave e-mail):</span><br/>
            <code>juliano.silva.oliveira@gmai.com</code>
            <div class='muted' style='margin-top:8px'>Versão {VERSION}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
