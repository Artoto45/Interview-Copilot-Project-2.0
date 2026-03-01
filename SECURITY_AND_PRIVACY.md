# 🔐 SEGURIDAD Y PRIVACY — Interview Copilot

**Información importante sobre datos sensibles**

---

## ⚠️ QUÉ NO ESTÁ EN ESTE REPOSITORIO

Por razones de seguridad y privacidad, los siguientes archivos **NO están en GitHub**:

### 🔑 API Keys y Credenciales
```
.env                          ← Contiene todas las API keys
.env.local                    ← Configuración local
NEVER commit esto a Git       ← ¡CRÍTICO!
```

**API Keys protegidas:**
- `OPENAI_API_KEY` (ChatGPT/embeddings)
- `ANTHROPIC_API_KEY` (Claude)
- `DEEPGRAM_API_KEY` (Transcription)
- `GOOGLE_API_KEY` (Gemini)

### 👤 Información Personal
```
kb/personal/*.txt             ← Tu resume, experiencia, perfil
(No está en GitHub)           ← Privacidad personal
```

**Archivos excluidos:**
- `perfil_*.txt` (tu perfil profesional)
- `historias_*.txt` (tus historias STAR)
- `resume.txt` (tu resume)

### 🏢 Información de Negocio
```
kb/company/*.txt              ← Info de empresa objetivo
(No está en GitHub)           ← Confidencialidad empresarial
```

**Archivos excluidos:**
- `company_profile.txt`
- `job_description.txt`
- `sample.txt`
- `projection_management.txt`

### 📊 Logs de Sesión
```
logs/interview_*.md           ← Transcripts de entrevistas
logs/metrics_*.json           ← Datos de performance
logs/costs_*.json             ← Datos de costos API
(No están en GitHub)          ← Información personal/sensible
```

### 📁 Datos Generados
```
chroma_data/                  ← ChromaDB vectorstore
*.faiss                       ← FAISS embeddings
*.pkl                         ← Serialized data
(No están en GitHub)          ← Archivos de sistema local
```

---

## ✅ QUÉ SÍ ESTÁ EN ESTE REPOSITORIO

### 📄 Código Fuente (Safe)
```
src/
├─ audio/
├─ transcription/
├─ knowledge/
├─ response/
├─ teleprompter/
├─ metrics.py
├─ alerting.py
├─ prometheus.py
└─ cost_calculator.py
```

### 📚 Documentación
```
README.md
ANALISIS_TECNICO_COMPLETO.md
DIAGRAMAS_Y_CASOS_DE_USO.md
QUICK_REFERENCE_FINAL.md
```

### 🔧 Configuración Template
```
.env.example              ← TEMPLATE (no contiene valores reales)
requirements.txt          ← Dependencias Python
.gitignore               ← Reglas de exclusión
```

### 🧪 Tests
```
tests/
├─ test_audio.py
├─ test_knowledge.py
├─ test_latency.py
└─ test_question_filter.py
```

---

## 🚀 CÓMO CLONAR Y USAR

### 1. Clonar el Repositorio
```bash
git clone https://github.com/[tu-usuario]/interview-copilot.git
cd interview-copilot
```

### 2. Crear tu .env Local
```bash
# Copiar template
cp .env.example .env

# Editar con tus datos (NO commitar esto)
nano .env    # o tu editor favorito

# Ejemplo de .env completado:
OPENAI_API_KEY=sk_...
ANTHROPIC_API_KEY=sk-ant-...
DEEPGRAM_API_KEY=...
# etc.
```

### 3. Agregar tu Knowledge Base
```bash
# Crear tus archivos personales (NO se van a Git)
mkdir -p kb/personal kb/company

# Agregar tus documentos
cat > kb/personal/resume.txt << EOF
[Tu resume aquí]
EOF

cat > kb/company/job_description.txt << EOF
[Descripción del trabajo aquí]
EOF
```

### 4. Instalar y Ejecutar
```bash
# Setup
python -m venv venv
source venv/bin/activate  # o: venv\Scripts\activate (Windows)
pip install -r requirements.txt

# Ingestar KB (genera chroma_data/ local)
python -c "from src.knowledge.ingest import KnowledgeIngestor; \
           KnowledgeIngestor().ingest_all()"

# Ejecutar
python main.py
```

---

## 🔐 SEGURIDAD: CHECKLIST ANTES DE PUSH

Antes de hacer `git push`, verifica:

```bash
# 1. Verificar que .env NO está staged
git status
# ❌ Si ves .env: problema
# ✅ Si NO ves .env: correcto

# 2. Verificar que kb/personal NO está staged
git status | grep kb/personal
# ❌ Si ves archivos: problema
# ✅ Si está vacío o solo .gitkeep: correcto

# 3. Verificar que logs NO está staged
git status | grep logs
# ❌ Si ves interview_*.md: problema
# ✅ Si está vacío o solo .gitkeep: correcto

# 4. Listar qué se va a pushear
git diff --cached --name-only
# Revisar que NO contiene .env, kb/*, logs/*

# 5. Si cometiste un error, revert:
git reset HEAD .env
git reset HEAD kb/personal/
git reset HEAD logs/
```

---

## 🛡️ SI ACCIDENTALMENTE COMMITTEASTE INFORMACIÓN SENSIBLE

### Rápido (archivos no pusheados aún):
```bash
# 1. Undo del último commit
git reset --soft HEAD~1

# 2. Unstage los archivos sensibles
git reset HEAD .env kb/personal/

# 3. Commit de nuevo sin ellos
git commit -m "Fix: remove sensitive files from commit"

# 4. Verificar antes de push
git log --stat -1
```

### Intermedio (ya pusheado):
```bash
# Si ya está en GitHub pero quieres limpiarlo:
# 1. Remove archivo del historial (DESTRUCTIVO)
git filter-branch --tree-filter 'rm -f .env' -- --all

# 2. Force push (cuidado: reescribe historial)
git push origin master --force-with-lease

# 3. O crear nuevo repositorio (más seguro)
```

### Crítico (API keys expuestas):
```bash
# 1. INMEDIATAMENTE: Rotar/revocar todas las API keys
#    - OpenAI: Cancel/regenerate API key
#    - Anthropic: Rotate key
#    - Deepgram: Rotate key
#    - Google: Disable/regenerate

# 2. Notificar a los servicios (si tienes cuenta comercial)

# 3. Limpiar historio de Git
git filter-branch --tree-filter 'rm -f .env' -- --all
git push origin master --force-with-lease

# 4. GitHub: Settings → Secrets (si las uses en Actions)
```

---

## 📋 ESTRUCTURA DE DIRECTORIOS PRIVADOS

```
Interview_Copilot/
├─ kb/
│  ├─ personal/              ← 🔒 PRIVADO (not in Git)
│  │  ├─ .gitkeep
│  │  ├─ resume.txt         (your resume)
│  │  ├─ skills.txt         (your skills)
│  │  ├─ experience.txt     (your experience)
│  │  └─ historias_*.txt    (your STAR stories)
│  │
│  └─ company/               ← 🔒 PRIVADO (not in Git)
│     ├─ .gitkeep
│     ├─ job_description.txt
│     ├─ company_profile.txt
│     └─ company_values.txt
│
├─ logs/                     ← 🔒 PRIVADO (not in Git)
│  ├─ .gitkeep
│  ├─ interview_*.md        (session transcripts)
│  ├─ metrics_*.json        (performance data)
│  └─ costs_*.json          (API costs)
│
├─ chroma_data/              ← 🔒 PRIVADO (not in Git)
│  ├─ chroma.sqlite3
│  └─ [embeddings...]
│
├─ .env                      ← 🔒 CRÍTICO (NEVER in Git)
│  (contains all API keys)
│
└─ .env.example              ← ✅ PUBLIC (template only)
   (no actual values)
```

---

## 📖 INSTRUCCIONES PARA CLONAR

Para alguien que clona tu repositorio:

```bash
# 1. Clone
git clone https://github.com/[tu-user]/interview-copilot

# 2. Setup environment
cp .env.example .env
# [Edit .env with YOUR api keys]

# 3. Create KB
mkdir -p kb/personal kb/company
# [Add your personal/company files]

# 4. Install
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Ingest KB
python -c "from src.knowledge.ingest import KnowledgeIngestor; \
           KnowledgeIngestor().ingest_all()"

# 6. Run
python main.py
```

**Nota:** Los archivos en `.gitignore` NO se descargarán. Cada usuario debe agregar los suyos.

---

## ✅ GITHUB ACTIONS SECURITY (OPTIONAL)

Si usas GitHub Actions:

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    steps:
      - uses: actions/checkout@v2
      - name: Run tests
        run: |
          python -m venv venv
          source venv/bin/activate
          pip install -r requirements.txt
          pytest tests/
```

**NUNCA hardcodees secrets en el código.**

---

## 🔍 VERIFICAR QUE GIT ESTÁ LIMPIO

```bash
# Ver qué archivos van a ser committeados
git status

# Ver tamaño de repo
du -sh .git

# Verificar ningún .env
git ls-files | grep ".env"
# ❌ Output = problema
# ✅ Empty output = bueno

# Verificar ningún archivo personal
git ls-files | grep "kb/personal"
# ❌ Si ves algo = problema
# ✅ Si está vacío = bueno
```

---

## 📞 RESUMEN SEGURIDAD

| Archivo | En GitHub | En .gitignore | Acción |
|---------|-----------|---------------|--------|
| `.env` | ❌ NO | ✅ SÍ | CREAR LOCALMENTE |
| `.env.example` | ✅ SÍ | ❌ NO | Template template |
| `kb/personal/*` | ❌ NO | ✅ SÍ | Crear localmente |
| `kb/company/*` | ❌ NO | ✅ SÍ | Crear localmente |
| `logs/*` | ❌ NO | ✅ SÍ | Generado localmente |
| `chroma_data/` | ❌ NO | ✅ SÍ | Generado localmente |
| `src/**` | ✅ SÍ | ❌ NO | Código público |
| `tests/**` | ✅ SÍ | ❌ NO | Tests públicos |
| `README.md` | ✅ SÍ | ❌ NO | Documentación |
| `requirements.txt` | ✅ SÍ | ❌ NO | Dependencias públicas |

---

**Generado:** 1 de Marzo de 2026
**Versión:** Interview Copilot v4.0
**Estado:** 🔐 Seguro para GitHub

