# 🚀 GUÍA: SUBIR A GITHUB SEGURO

**Paso a paso para subir Interview Copilot a GitHub**

---

## 📋 PRE-CHECKLIST

Antes de nada, verifica:

```bash
# 1. Ir a directorio del proyecto
cd "C:\Users\artot\OneDrive\Desktop\Carpeta_Proyecto_Desarrollo_Software\Interview_Proyect\Nueva_Versión_2.0"

# 2. Git ya inicializado? (busca .git/)
ls -la | grep ".git"
# ✅ Si ves ".git/" → listo
# ❌ Si no ves ".git/" → ejecuta: git init
```

---

## PASO 1: Verificar que .gitignore está actualizado

```bash
# Ver contenido
cat .gitignore

# Verificar que contiene:
# ✅ .env
# ✅ kb/personal/
# ✅ kb/company/
# ✅ logs/
# ✅ chroma_data/

# Si faltan, ejecuta:
# (ya lo hemos actualizado, pero verifica)
```

---

## PASO 2: Verificar que NO hay archivos sensibles staged

```bash
# Ver estado
git status

# Debe mostrar:
# On branch master
# nothing to commit, working tree clean

# O si hay cambios, verifica que NO contienen:
# ❌ .env
# ❌ perfil_luis_araujo.txt
# ❌ historias_star.txt
# ❌ interview_*.md

# Si accidentalmente staged algo sensible:
git reset HEAD [archivo_sensible]
```

---

## PASO 3: Crear README para GitHub

Ya existe, pero asegúrate que contiene:
- ✅ Descripción del proyecto
- ✅ Setup instructions
- ✅ Link a SECURITY_AND_PRIVACY.md
- ✅ License (opcional)

---

## PASO 4: Crear repositorio en GitHub

1. Ve a https://github.com/new
2. Rellena:
   - **Repository name:** `interview-copilot`
   - **Description:** "Real-time AI interview copilot assistant with RAG knowledge base"
   - **Visibility:** Public (si quieres compartir) o Private
   - **NO inicialices con README** (ya lo tienes)
3. Click "Create repository"

GitHub te mostrará comandos. Aquí están los que necesitas:

---

## PASO 5: Agregar repositorio remoto

```bash
# Navegar al proyecto
cd C:\Users\artot\OneDrive\Desktop\Carpeta_Proyecto_Desarrollo_Software\Interview_Proyect\Nueva_Versión_2.0

# Agregar GitHub como remote
git remote add origin https://github.com/[TU-USUARIO]/interview-copilot.git

# Verificar
git remote -v
# Debe mostrar:
# origin  https://github.com/[TU-USUARIO]/interview-copilot.git (fetch)
# origin  https://github.com/[TU-USUARIO]/interview-copilot.git (push)
```

---

## PASO 6: Verificar qué se va a subir (CRÍTICO)

```bash
# Ver todos los archivos que se van a subir
git ls-files

# VERIFICAR que NO contiene:
# ❌ .env (debe estar en .gitignore)
# ❌ chroma_data/ (debe estar en .gitignore)
# ❌ kb/personal/*.txt (debe estar en .gitignore)
# ❌ kb/company/*.txt (debe estar en .gitignore)
# ❌ logs/*.md, logs/*.json (debe estar en .gitignore)

# Si alguno aparece ERRÓNEAMENTE:
git rm --cached [archivo]  # Remove from Git (keep locally)
git commit -m "Remove [archivo] from tracking"

# Ejemplo:
git rm --cached .env
git commit -m "Remove .env from version control"
```

---

## PASO 7: Hacer el PRIMER commit

```bash
# Stage todos los cambios
git add .

# Crear commit
git commit -m "Initial commit: Interview Copilot v4.0

- Real-time AI interview assistant with RAG knowledge base
- Dual audio transcription (OpenAI Realtime + Deepgram)
- Multi-model response generation (Claude/OpenAI/Gemini)
- PyQt5 teleprompter overlay
- Cost tracking and metrics
- Comprehensive documentation

Security: No API keys, personal data, or business info included.
See SECURITY_AND_PRIVACY.md for details."

# Ver el commit
git log --oneline -1
# Debe mostrar algo como:
# abc1234 Initial commit: Interview Copilot v4.0
```

---

## PASO 8: Push a GitHub

```bash
# Push al branch master/main
git push -u origin master
# O si tu rama default es main:
git push -u origin main

# Pedirá autenticación (GitHub):
# Opción A: Token personal (recomendado)
#   1. Ve a https://github.com/settings/tokens
#   2. Click "Generate new token"
#   3. Selecciona: repo, write:packages, delete:packages
#   4. Copia el token
#   5. Pega en la prompt de Git
#
# Opción B: SSH (más seguro)
#   1. ssh-keygen -t ed25519
#   2. cat ~/.ssh/id_ed25519.pub
#   3. Agrega a GitHub: Settings → SSH and GPG keys
#   4. Usa: git remote set-url origin git@github.com:[USER]/interview-copilot.git

# Espera a que termine...
# Output final:
# branch 'master' set up to track 'origin/master'.
```

---

## PASO 9: Verificar en GitHub

1. Ve a https://github.com/[TU-USUARIO]/interview-copilot
2. Verifica:
   - ✅ Archivos están ahí (src/, tests/, docs, README.md)
   - ✅ .env NO está
   - ✅ chroma_data/ NO está
   - ✅ kb/personal/ vacío (solo .gitkeep)
   - ✅ kb/company/ vacío (solo .gitkeep)
   - ✅ logs/ vacío (solo .gitkeep)

---

## PASO 10: Agregar descripción y topics (OPCIONAL)

En GitHub:
1. Click "About" (lado derecho)
2. **Description:** "Real-time AI interview copilot with RAG knowledge base"
3. **Website:** (si tienes)
4. **Topics:** Add:
   - `interview-prep`
   - `ai-assistant`
   - `rag`
   - `chromadb`
   - `realtime-api`
   - `claude`
   - `openai`
5. Click "Save"

---

## PASO 11: Crear .gitkeep donde falta

Ya lo hicimos, pero verifica que existen:
```bash
ls -la kb/personal/.gitkeep
ls -la kb/company/.gitkeep
ls -la logs/.gitkeep
```

---

## FUTUROS COMMITS: Workflow

Para próximos cambios:

```bash
# 1. Hacer cambios en código

# 2. Ver qué cambió
git status

# 3. Stage cambios (EXCLUYE sensibles)
git add src/
git add tests/
git add *.md

# 4. Verificar
git status
# Debe mostrar VERDE (staged) para código
# NO debe mostrar .env, kb/personal/, logs/, chroma_data/

# 5. Commit
git commit -m "Feature: [descripción breve]"

# 6. Push
git push origin master
```

---

## ⚠️ IMPORTANTE: PROTEGER main BRANCH

En GitHub:
1. Settings → Branches
2. Click "Add rule"
3. Branch name pattern: `master` (o `main`)
4. Habilita:
   - ✅ Require pull request reviews before merging
   - ✅ Require status checks to pass
5. Click "Create"

Esto previene que accidentalmente se pushee sensible info.

---

## 🔒 VERIFICACIÓN FINAL ANTES DE PUBLICAR

```bash
# Último check: no debería tener archivos sensibles
git ls-files | grep -E "(\.env|\.pem|\.key|perfil_|historias_|interview_)"

# Si es vacío: ✅ SEGURO
# Si hay algo: ❌ NO PUSHEES
```

---

## 📊 CHECKLIST FINAL

Antes de ir a **Settings → Make public** (si está private):

- ✅ .env NO está en repo
- ✅ kb/personal/ sin archivos sensibles
- ✅ kb/company/ sin archivos sensibles
- ✅ logs/ vacío
- ✅ chroma_data/ NO está
- ✅ README.md tiene instrucciones
- ✅ SECURITY_AND_PRIVACY.md existe
- ✅ Primer commit pusheado
- ✅ GitHub repo existe
- ✅ Branch protection configurado

---

## 🎉 LISTO!

Tu repositorio está seguro en GitHub. Ahora puedes:

1. **Compartir el link** con otros developers
2. **Colaborar** con seguridad
3. **CI/CD** si lo necesitas (GitHub Actions)
4. **Documentación pública** visible

---

## 📞 TROUBLESHOOTING

### Error: "repository not found"
```bash
# Solución: Verificar URL
git remote -v

# Cambiar si es necesario:
git remote set-url origin https://github.com/[CORRECTO]/interview-copilot.git
```

### Error: "Authentication failed"
```bash
# Solución 1: Token personal
# https://github.com/settings/tokens
# Genera nuevo token, copia, pega en prompt

# Solución 2: SSH
ssh-keygen -t ed25519
cat ~/.ssh/id_ed25519.pub
# Agrega a: https://github.com/settings/ssh/new
git remote set-url origin git@github.com:[USER]/interview-copilot.git
```

### Error: "branch is ahead of origin"
```bash
# Ya hace push, pero no "set upstream"
git push -u origin master
```

### Error: "would be overwritten by merge"
```bash
# Archivos en conflicto, stash primero
git stash
git pull
git stash pop
```

---

**Guía completada:** 1 de Marzo de 2026
**Estado:** 🚀 Listo para GitHub

