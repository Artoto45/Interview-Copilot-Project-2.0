@echo off
cd "C:\Users\artot\OneDrive\Desktop\Carpeta_Proyecto_Desarrollo_Software\Interview_Proyect\Nueva_Versión_2.0"
echo.
echo ============================================
echo Verificando repositorio Git
echo ============================================
echo.
git status
echo.
echo ============================================
echo Último commit
echo ============================================
echo.
git log --oneline -1
echo.
echo ============================================
echo Remoto configurado
echo ============================================
echo.
git remote -v
echo.
echo ============================================
echo Haciendo push a GitHub...
echo ============================================
echo.
git push -u origin main
echo.
echo ============================================
echo Push completado
echo ============================================
echo.
pause

