# GUÍA DE SEGURIDAD Y PRIVACIDAD — Interview Copilot

**Antes de subir a GitHub, verifica estas secciones críticas.**

---

## 🔴 INFORMACIÓN SENSIBLE QUE NO DEBE ESTAR EN GITHUB

### 1. **Archivos .env**
```bash
.env  ← NUNCA subir este archivo
.env.example  ← OK subir (sin valores reales)
```

**Archivo .env actual (NO SUBIR):**
```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
DEEPGRAM_API_KEY=...
VOICEMEETER_DEVICE_USER=...
VOICEMEETER_DEVICE_INT=...
LOOPBACK_GAIN=2.0
WS_HOST=127.0.0.1
WS_PORT=8765
PROMETHEUS_PORT=8000
```

**Crear .env.example (subir esto):**
```bash
# OpenAI APIs
OPENAI_API_KEY=your_openai_api_key_here

# Anthropic Claude
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Deepgram
DEEPGRAM_API_KEY=your_deepgram_api_key_here

# Audio Configuration
AUDIO_SAMPLE_RATE=16000
AUDIO_CHUNK_MS=100
VOICEMEETER_DEVICE_USER=VoiceMeeter Out B1
VOICEMEETER_DEVICE_INT=VoiceMeeter Out B2
LOOPBACK_GAIN=2.0

# Server Configuration
WS_HOST=127.0.0.1
WS_PORT=8765
PROMETHEUS_PORT=8000
```

---

### 2. **Archivos a Excluir en .gitignore**

```bash
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# Virtual environments
venv/
ENV/
env/
.venv

# IDE
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store

# Environment variables
.env
.env.local
.env.*.local

# Credentials & Secrets
*.key
*.pem
*.p12
*.pfx
secrets/
credentials/
api_keys/

# Data & Logs (contienen información personal)
logs/
*.log
chroma_data/
*.db
*.sqlite
*.sqlite3

# Audio files (pueden contener voces reales)
*.wav
*.mp3
*.m4a
*.flac

# Session files
interview_*.md
costs_*.json
metrics_*.json

# OS
Thumbs.db
.DS_Store

# Testing
.pytest_cache/
.coverage
htmlcov/

# Temporary
*.tmp
*.temp
*.bak
/temp/
```

---

### 3. **Información Personal en Código**

❌ **NO INCLUIR:**
```python
# Nombres reales
CANDIDATE_NAME = "Luis Araujo"
COMPANY_NAME = "Webhelp"
CANDIDATE_EMAIL = "luis@example.com"
CANDIDATE_PHONE = "+1234567890"

# Ubicaciones específicas
OFFICE_ADDRESS = "123 Main St, City"
CANDIDATE_LOCATION = "Madrid, Spain"

# Credenciales
PASSWORD_EXAMPLES = "admin123"
API_KEY_SAMPLES = "sk-1234567890abcdef"

# Datos de entrevista reales
INTERVIEW_ANSWERS = {
    "Tell me about yourself": "I worked at [Real Company]...",
    "Your strengths": "I'm good at [Real Project]...",
}
```

✅ **USAR PLACEHOLDERS:**
```python
# Nombres genéricos
CANDIDATE_NAME = "[Your Name]"
COMPANY_NAME = "[Target Company Name]"

# Datos de ejemplo
SAMPLE_KB_CHUNKS = [
    "I have 5+ years of experience in Python development",
    "I've worked on distributed systems and cloud infrastructure",
]

# Variables de entorno
from dotenv import load_dotenv
import os
CANDIDATE_NAME = os.getenv("CANDIDATE_NAME", "[Candidate Name]")
```

---

### 4. **Archivos de Datos Sensibles**

```bash
logs/
├── interview_2026-03-01_10-24.md  ← CONTIENE RESPUESTAS REALES
├── metrics_session_*.json          ← OK (solo métricas)
└── costs_session_*.json            ← OK (solo costos)

chroma_data/
└── [Embeddings de KB personal]     ← INCLUIR .gitignore

kb/
├── personal/                        ← Tus respuestas personalizadas
│   ├── about_you.md
│   ├── strengths.md
│   └── experience.md
└── company/                         ← Información de empresa
    └── company_research.md
```

**Decisión:** Incluir estructura `kb/` con ejemplos, pero NO archivos reales.

---

## 🟡 INFORMACIÓN DE NEGOCIO

### Datos que NUNCA deben estar en público:

1. **Presupuestos de Trabajo Actual**
   - Salario
   - Beneficios
   - Negociaciones

2. **Información de Empresas Específicas**
   - Procesos internos de entrevista
   - Personas de contacto reales
   - Estructuras organizacionales privadas

3. **Estrategia de Búsqueda de Trabajo**
   - Lista de empresas objetivo
   - Marcos de tiempo
   - Números de aplicaciones

---

## 🟢 INFORMACIÓN QUE SÍ PUEDE ESTAR EN GITHUB

✅ **Código de la Aplicación**
- Toda la lógica de `src/`
- Flujos de procesamiento
- Arquitectura

✅ **Configuración General**
- `requirements.txt` (sin valores)
- `.env.example`
- `main.py`
- Estructura de directorios

✅ **Documentación**
- README.md con instrucciones
- Diagrama de arquitectura
- Documentación técnica (este archivo)

✅ **Ejemplos Genéricos**
```python
# Chunk de ejemplo para KB
{
    "text": "I have experience with Python, JavaScript, and SQL",
    "category": "personal",
    "topic": "technical_skills",
}
```

✅ **Tests**
- Todos los archivos en `tests/`
- No contienen datos personales

---

## 📋 CHECKLIST ANTES DE SUBIR A GITHUB

```bash
# 1. Verificar .env no está en staging
git status
# NO debe mostrar: .env

# 2. Verificar .gitignore está completo
cat .gitignore
# Debe incluir: .env, logs/, chroma_data/, kb/personal/, *.wav, etc.

# 3. Buscar credenciales en código
grep -r "sk-" src/  # No debe encontrar nada
grep -r "OPENAI_API_KEY=" src/  # No debe haber valores hardcodeados

# 4. Verificar logs/ está excluido
git status logs/
# Debe decir: "nothing to commit"

# 5. Verificar archivos personales están excluidos
git status kb/personal/
# Debe estar en .gitignore

# 6. Simulación final de push (dry-run)
git diff --cached
# Revisar solo archivos permitidos

# 7. Push seguro
git push origin main
```

---

## 🔐 INSTRUCCIONES PARA CLONAR Y USAR

### Para Otros Desarrolladores:

```bash
# 1. Clonar repo
git clone https://github.com/artoto45-ship-it/Interview-Copilot-Project.git

# 2. Crear .env local (NUNCA commitear)
cp .env.example .env

# 3. Llenar con tus credenciales (LOCALES SOLAMENTE)
nano .env
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# etc.

# 4. Crear tu KB personal (NO subir a GitHub)
mkdir -p kb/{personal,company}
echo "I have 5+ years of Python experience" > kb/personal/experience.md

# 5. Instalar y ejecutar
pip install -r requirements.txt
python main.py
```

---

## 🛡️ MEDIDAS DE SEGURIDAD IMPLEMENTADAS

### En el Código:

```python
# ✅ CORRECTO: Variables de entorno
from dotenv import load_dotenv
import os

load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")  # Del .env, no hardcodeado

# ❌ INCORRECTO: Hardcodeado
API_KEY = "sk-1234567890abcdef"  # ¡NUNCA!
```

### En Git:

```bash
# ✅ .gitignore fuerte
.env
.env.*
!.env.example
secrets/
*.key

# ✅ Verificar antes de cada push
git diff --cached | grep -i "key\|secret\|password"
# No debe encontrar nada
```

### En GitHub:

```
1. Repo PÚBLICO: Solo código de aplicación
2. Secrets: Usar GitHub Secrets para CI/CD
3. Branches: main (limpio) + dev (experimental)
4. Reviews: Verificar no hay secretos antes de merge
```

---

## 📝 TEMPLATE: README.md SEGURO

```markdown
# Interview Copilot v4.0

Advanced real-time interview preparation assistant with dual-channel 
transcription, semantic knowledge retrieval, and streaming response generation.

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Voicemeeter Banana (for dual audio capture)
- API keys (OpenAI, Deepgram)

### Installation

```bash
git clone https://github.com/artoto45-ship-it/Interview-Copilot-Project.git
cd Interview-Copilot-Project

# Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install deepgram-sdk

# Setup environment (template provided)
cp .env.example .env
# Edit .env with your API keys
nano .env
```

### Usage

```bash
python main.py
```

Your interview copilot will be ready in 3 seconds!

## 🔐 Security

- **Never commit `.env` files** — use `.env.example` template
- **Keep credentials local** — use environment variables only
- **No personal KB data** — gitignore covers `kb/personal/`
- **Session logs** — excluded from git, stored locally

See [SECURITY_AND_PRIVACY.md](SECURITY_AND_PRIVACY.md) for details.

## 📊 Architecture

See [DOCUMENTACION_TECNICA_COMPLETA.md](DOCUMENTACION_TECNICA_COMPLETA.md)

## 📄 License

MIT License — See LICENSE file
```

---

## ⚠️ POST-GITHUB CHECKLIST

Después de subir a GitHub:

```bash
# 1. Verificar en GitHub UI que .env NO está
# GitHub.com → tu repo → No buscar archivos .env

# 2. Verificar no hay logs accidentales
# Buscar: "interview_" en repo
# Resultado: Nada (excluido por .gitignore)

# 3. Verificar KB personal no está incluido
# Búsqueda: kb/personal/
# Resultado: Nada

# 4. Revisar todo el árbol de archivos
# GitHub → Code → Revisar estructura
# Debe mostrar: src/, tests/, docs/, main.py, README.md, pero NO .env

# 5. Test: Clonar en otra máquina
cd /tmp
git clone https://github.com/artoto45-ship-it/Interview-Copilot-Project.git
ls -la Interview-Copilot-Project/
# Verificar:
# - .env NO está ✓
# - .env.example SÍ está ✓
# - kb/personal/ NO está ✓
# - kb/company/ existe pero vacío ✓
```

---

## 🚨 EN CASO DE EMERGENCIA

Si accidentalmente committeaste un secreto:

```bash
# 1. INMEDIATAMENTE: Revoke el API key en OpenAI/Anthropic/Deepgram
# https://platform.openai.com/account/api-keys
# Delete compromised key, create new one

# 2. Eliminar commit del historio de Git
# Option A (rewrite history — nuclear):
git filter-branch --force --tree-filter 'rm -f .env' HEAD
git push origin main --force-with-lease

# Option B (simpler — just remove file):
git rm --cached .env
echo ".env" >> .gitignore
git add .gitignore
git commit -m "Remove .env (never commit secrets)"
git push origin main

# 3. Crear nuevo .env local con nuevas credenciales
cp .env.example .env
# Llenar con las nuevas API keys

# 4. Notificar a otros desarrolladores
# "Revoked old API keys, please use new ones in .env"
```

---

## 📚 REFERENCIAS

- [GitHub: Removing Sensitive Data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
- [OWASP: Secret Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [Python-dotenv Best Practices](https://python-dotenv.readthedocs.io/)

---

**Última Revisión:** 1 de Marzo, 2026
**Estado:** ✅ Listo para GitHub

Verifica este checklist ANTES de hacer `git push`.

