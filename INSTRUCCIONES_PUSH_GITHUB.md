# INSTRUCCIONES FINALES: PUSH A GITHUB SEGURO

**Fecha:** 1 de Marzo de 2026  
**Versión:** Interview Copilot v4.0

---

## ✅ CHECKLIST PRE-PUSH (OBLIGATORIO)

Antes de hacer cualquier push a GitHub, completa TODOS estos puntos:

### 1. Verificación de .gitignore

```bash
# Verificar que .gitignore existe y es completo
cat .gitignore
```

**Debe contener (mínimo):**
```
.env
.env.*
!.env.example
logs/
*.log
chroma_data/
__pycache__
*.pyc
venv/
.venv
kb/personal
*.wav
*.mp3
*.db
*.sqlite3
.pytest_cache/
.coverage
```

### 2. Verificación de Archivos Sensibles

```bash
# ❌ NUNCA deben estar en staging:
git status | grep -E "\.env$|\.env\.local|logs/|chroma_data|kb/personal"
# → Si encuentra algo → DETENER y agregar a .gitignore

# ✅ DEBE estar en staging:
git status | grep -E "\.env\.example|src/|tests/|main\.py|README|requirements\.txt"
# → Continuar
```

### 3. Buscar Secrets en Código

```bash
# Buscar hardcoded API keys
git diff --cached | grep -iE "sk-|OPENAI_API_KEY|ANTHROPIC_API_KEY|password"
# → Si encuentra algo → ❌ NUNCA commitear

# Alternativa: usar herramienta
pip install detect-secrets
detect-secrets scan --list-all-plugins > .secrets.baseline
# → Revisar reporte
```

### 4. Verificar Archivos NO Permitidos

```bash
# Listar archivos en staging
git diff --cached --name-only

# ❌ PROHIBIDOS:
.env
.env.local
logs/*.md
logs/*.json
interview_*.md
costs_*.json
chroma_data/*
kb/personal/*
*.wav
*.mp3

# ✅ PERMITIDOS:
src/**
tests/**
main.py
requirements.txt
.env.example
README.md
.gitignore
```

---

## 🚀 PASOS DE PUSH (PASO A PASO)

### Opción 1: Usando Script Automatizado (RECOMENDADO)

```bash
# 1. Verificar sin hacer nada
python push_safe_to_github.py --check

# 2. Si todo está OK:
python push_safe_to_github.py --push

# 3. Confirmar cuando pida "yes"
```

### Opción 2: Manual (Con máximo control)

```bash
# 1. Revisar cambios
git status

# 2. Ver exactamente qué se va a commitear
git diff --cached | head -50

# 3. Staging (si NO está ya staged)
git add src/
git add main.py
git add requirements.txt
git add .gitignore
git add README.md
git add DOCUMENTACION_TECNICA_COMPLETA.md
git add GUIA_SEGURIDAD_GITHUB.md
git add push_safe_to_github.py
git add .env.example

# 4. VERIFICAR DE NUEVO (crítico)
git status --porcelain
# ❌ Si hay .env → unstage: git restore --staged .env
# ❌ Si hay logs/ → unstage: git restore --staged logs/

# 5. Commit
git commit -m "Initial commit: Interview Copilot v4.0 - Production release"

# 6. Verificar antes de push
git log --oneline -1
git show --stat

# 7. Push final
git push origin main
```

---

## 🔍 VERIFICACIÓN FINAL (CRÍTICA)

### Antes de hacer push, ejecutar:

```bash
#!/bin/bash
set -e

echo "═════════════════════════════════════════════════════════"
echo "  VERIFICACIÓN FINAL PRE-PUSH"
echo "═════════════════════════════════════════════════════════"
echo ""

# 1. .env file check
echo "✓ Verificando .env no está en staging..."
if git diff --cached --name-only | grep -q "^\.env$"; then
    echo "❌ ERROR: .env está en staging"
    exit 1
fi

# 2. Secrets check
echo "✓ Buscando secrets en código..."
if git diff --cached | grep -iE "sk-[a-zA-Z0-9]{48}|OPENAI_API_KEY.*=|password.*=.*['\"]" 2>/dev/null | grep -v "^[+-].*#"; then
    echo "❌ ERROR: Posible secret encontrado"
    exit 1
fi

# 3. Personal KB check
echo "✓ Verificando kb/personal no está..."
if git diff --cached --name-only | grep "^kb/personal"; then
    echo "❌ ERROR: kb/personal/ está en staging"
    exit 1
fi

# 4. Logs check
echo "✓ Verificando logs no están..."
if git diff --cached --name-only | grep "^logs/"; then
    echo "❌ ERROR: logs/ están en staging"
    exit 1
fi

# 5. Count files
echo "✓ Contando archivos..."
file_count=$(git diff --cached --name-only | wc -l)
echo "  Total: $file_count archivos"

if [ $file_count -lt 5 ]; then
    echo "⚠️  WARNING: Muy pocos archivos ($file_count)"
fi

# 6. List files
echo ""
echo "Archivos en staging:"
git diff --cached --name-only | sed 's/^/  /'

echo ""
echo "═════════════════════════════════════════════════════════"
echo "  ✅ VERIFICACIÓN COMPLETADA — OK PARA PUSH"
echo "═════════════════════════════════════════════════════════"
```

Guardar como `verify_push.sh` y ejecutar:
```bash
chmod +x verify_push.sh
./verify_push.sh
```

---

## 📋 EN GITHUB: QUÉ DEBE VERSE

### URL del Repositorio:
```
https://github.com/artoto45-ship-it/Interview-Copilot-Project
```

### Estructura Visible en GitHub:

```
Interview-Copilot-Project/
│
├── src/                           ✅ Visible
│   ├── audio/
│   ├── transcription/
│   ├── knowledge/
│   ├── response/
│   └── teleprompter/
│
├── tests/                         ✅ Visible
│
├── main.py                        ✅ Visible
├── requirements.txt               ✅ Visible
├── .env.example                   ✅ Visible
├── .gitignore                     ✅ Visible
│
├── README_GITHUB.md               ✅ Visible (copiar a README.md)
├── DOCUMENTACION_TECNICA_COMPLETA.md  ✅ Visible
├── GUIA_SEGURIDAD_GITHUB.md       ✅ Visible
│
└── push_safe_to_github.py         ✅ Visible

❌ NO debe verse:
.env (valores reales)
logs/
chroma_data/
kb/personal/
*.wav, *.mp3
__pycache__
.venv/
```

### Verificación en GitHub UI:

1. Ir a: https://github.com/artoto45-ship-it/Interview-Copilot-Project
2. Click en "Code" → revisar árbol de archivos
3. **Confirmar:**
   - ✅ src/ está presente
   - ✅ main.py está presente
   - ✅ requirements.txt está presente
   - ❌ .env NO está (solo .env.example)
   - ❌ logs/ NO está
   - ❌ chroma_data/ NO está
   - ❌ kb/personal/ NO está

---

## ⚠️ SI ALGO SALE MAL

### "Accidentalmente committé .env"

```bash
# ¡INMEDIATAMENTE! Revoke tus API keys:
# https://platform.openai.com/account/api-keys (delete old key, create new)
# https://console.anthropic.com/account/keys (delete old key, create new)
# https://console.deepgram.com/keys (delete old key, create new)

# Rewrite git history (NUCLEAR):
git filter-branch --force --tree-filter 'rm -f .env' HEAD
git push origin main --force-with-lease

# Create new .env locally with NEW API keys
cp .env.example .env
nano .env
```

### "Accidentalmente committé kb/personal"

```bash
# Método 1: Revert commit (safe)
git revert HEAD
git push origin main

# Método 2: Amend commit (if not yet pushed)
git rm --cached kb/personal/
echo "kb/personal/" >> .gitignore
git add .gitignore
git commit --amend
git push origin main
```

### "Puedo ver mis datos personales en GitHub"

```bash
# Verificar qué está visible
git ls-tree -r HEAD | grep -E "\.env|logs|kb/personal|\.wav"

# Si hay algo, usar git filter-branch para eliminar
git filter-branch --tree-filter 'find . -name "*.env" -delete' HEAD

# Force push (cuidado — destruye histórico)
git push origin main --force-with-lease

# Notificar a usuarios que clonasen (reclonen)
```

---

## 📞 DESPUÉS DEL PUSH: VERIFICACIÓN FINAL

### Test 1: Clonar en Máquina Diferente

```bash
# En otra máquina o carpeta temporal:
cd /tmp
git clone https://github.com/artoto45-ship-it/Interview-Copilot-Project.git
cd Interview-Copilot-Project

# Verificar estructura
ls -la
# Debe mostrar:
#   src/ → Sí
#   main.py → Sí
#   requirements.txt → Sí
#   .env → NO (✅ correcto)
#   logs/ → NO (✅ correcto)
#   kb/personal/ → NO (✅ correcto)
```

### Test 2: Verificar Búsqueda en GitHub

```bash
# En GitHub, usar búsqueda:
# https://github.com/artoto45-ship-it/Interview-Copilot-Project/search?q=OPENAI_API_KEY

# Resultado esperado: "No results found" ✅

# Buscar otros patrones:
# https://github.com/artoto45-ship-it/Interview-Copilot-Project/search?q=sk-

# Resultado esperado: "No results found" ✅
```

### Test 3: Verificar Archivos Grandes

```bash
# En GitHub → "Releases" o revisar tamaño de repo
# Si repo > 50MB, puede haber archivos innecesarios

# Localmente:
du -sh .git/
# Debe ser < 20MB (sin blobs enormes)
```

---

## 🎯 COMANDO FINAL (TODO EN UNO)

Si todo está verificado, el push final es simple:

```bash
# Opción A: Script automatizado
python push_safe_to_github.py --push

# Opción B: Git directo
git push origin main

# Confirmar salida:
# Enumerating objects: XXX
# Counting objects: 100% (XXX/XXX)
# Writing objects: 100% (XXX/XXX)
# remote: Resolving deltas: 100% (XXX/XXX)
# To github.com:artoto45-ship-it/Interview-Copilot-Project.git
#    [id123456]...[id789abc]  main -> main
```

---

## 📊 RESUMEN: ENTRADA VS SALIDA

### ❌ Lo que ENTRA en GitHub
```
- Source code (src/)
- Entry point (main.py)
- Dependencies (requirements.txt)
- Configuration template (.env.example)
- Documentation (README, guides)
- Tests (tests/)
```

### ✅ Lo que NO Entra (git-ignored)
```
- .env (your actual API keys)
- logs/ (session transcripts)
- chroma_data/ (your KB embeddings)
- kb/personal/ (your interview answers)
- Audio files (*.wav, *.mp3)
- Virtual environment (venv/)
```

### 🎯 Resultado Final
```
Public Repo: Interview Copilot v4.0
├── Code: 100% visible
├── Architecture: 100% documented
├── Security: ✅ Zero secrets exposed
└── Privacy: ✅ Zero personal data visible
```

---

## ✨ CONCLUSIÓN

**Estás listo para subir a GitHub de manera SEGURA.**

Pasos finales:

```bash
# 1. Ejecutar verificación
python push_safe_to_github.py --check

# 2. Si todo está OK, hacer push
python push_safe_to_github.py --push

# 3. Verificar en GitHub
# https://github.com/artoto45-ship-it/Interview-Copilot-Project

# ¡Éxito! 🎉
```

---

**Documentación generada:** 1 de Marzo de 2026  
**Status:** ✅ LISTO PARA PRODUCCIÓN

Cualquier duda: revisar [GUIA_SEGURIDAD_GITHUB.md](GUIA_SEGURIDAD_GITHUB.md)

