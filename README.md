# Contador de Histórias (Streamlit + Google AI Studio)

App de histórias infantis com guardrails + geração de ilustração opcional.

## Rodando local
1. `python -m venv .venv && source .venv/bin/activate` (Windows: `.\.venv\Scripts\activate`)
2. `pip install -r requirements.txt`
3. Crie `.env` com `GOOGLE_API_KEY`
4. `streamlit run streamlit_app.py`

## Deploy no Streamlit Cloud
- Conecte este repo.
- **Main file path**: `streamlit_app.py`
- Em **Secrets** do app, adicione:
  ```toml
  GOOGLE_API_KEY = "sua_chave"
