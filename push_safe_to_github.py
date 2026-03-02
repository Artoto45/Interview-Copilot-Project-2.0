#!/usr/bin/env python3
"""
Safe GitHub Push Script
=======================
Verifies no sensitive data before pushing to GitHub.

Usage:
    python push_to_github.py --check         # Solo verificar
    python push_to_github.py --push          # Verificar + push
    python push_to_github.py --force         # Push sin verificación (USE WITH CAUTION!)
"""

import os
import sys
import subprocess
import re
from pathlib import Path
from typing import List, Tuple

class GitSafetyChecker:
    """Verifica que no haya datos sensibles antes de push."""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.repo_root = Path(__file__).parent

    def check_gitignore(self) -> bool:
        """Verificar que .gitignore existe y es completo."""
        gitignore_path = self.repo_root / ".gitignore"

        if not gitignore_path.exists():
            self.errors.append("❌ .gitignore no existe")
            return False

        gitignore_content = gitignore_path.read_text()
        required_patterns = [
            ".env",
            "logs/",
            "chroma_data/",
            "*.wav",
            "*.mp3",
            "__pycache__",
        ]

        missing = []
        for pattern in required_patterns:
            if pattern not in gitignore_content:
                missing.append(pattern)

        if missing:
            self.errors.append(f"❌ .gitignore incompleto — falta: {', '.join(missing)}")
            return False

        print("✅ .gitignore está completo")
        return True

    def check_env_file(self) -> bool:
        """Verificar que .env NO está en staging."""
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(self.repo_root)
        )

        if ".env" in result.stdout:
            self.errors.append("❌ .env está en staging — NUNCA commitear")
            return False

        print("✅ .env no está en staging")
        return True

    def check_secrets_in_code(self) -> bool:
        """Buscar patrones de secrets en código."""
        dangerous_patterns = [
            (r'sk-[a-zA-Z0-9]{48}', "OpenAI API Key"),
            (r'sk-ant-[a-zA-Z0-9]+', "Anthropic API Key"),
            (r'password\s*=\s*["\'](?!your_|example_)', "Hardcoded Password"),
            (r'api_key\s*=\s*["\'](?!your_|example_)', "Hardcoded API Key"),
            (r'OPENAI_API_KEY\s*=\s*["\'](?!your_|example_)', "Hardcoded OpenAI Key"),
        ]

        # Archivos a excluir
        exclude_patterns = [".git/", "__pycache__", ".venv", "venv", "node_modules"]

        found_secrets = []

        for file_path in self.repo_root.rglob("*.py"):
            # Skip excluded directories
            if any(exc in str(file_path) for exc in exclude_patterns):
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                for pattern, label in dangerous_patterns:
                    if re.search(pattern, content):
                        found_secrets.append(f"{file_path.name}: {label}")
            except Exception:
                pass

        if found_secrets:
            for secret in found_secrets:
                self.errors.append(f"❌ Posible secret encontrado: {secret}")
            return False

        print("✅ No se encontraron secrets en código")
        return True

    def check_git_status(self) -> Tuple[bool, str]:
        """Verificar estado de git."""
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(self.repo_root)
        )

        staged = [line for line in result.stdout.split("\n") if line and line[0] in "MADRCU"]

        if not staged:
            self.warnings.append("⚠️ No hay cambios staged para commit")
            return False, ""

        print(f"✅ {len(staged)} archivos en staging:")
        for line in staged[:5]:
            print(f"   {line}")
        if len(staged) > 5:
            print(f"   ... y {len(staged) - 5} más")

        return True, result.stdout

    def check_logs_excluded(self) -> bool:
        """Verificar que logs/ no está en staging."""
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(self.repo_root)
        )

        if "logs/" in result.stdout:
            self.errors.append("❌ Archivos en logs/ están en staging — debe estar en .gitignore")
            return False

        print("✅ logs/ no está en staging")
        return True

    def run_all_checks(self) -> bool:
        """Ejecutar todas las verificaciones."""
        print("\n" + "="*60)
        print("  VERIFICACIÓN DE SEGURIDAD - GitHub Push")
        print("="*60 + "\n")

        checks = [
            ("Validando .gitignore...", self.check_gitignore),
            ("Verificando .env...", self.check_env_file),
            ("Escaneando secrets...", self.check_secrets_in_code),
            ("Revisando logs/...", self.check_logs_excluded),
            ("Verificando staging...", lambda: self.check_git_status()[0]),
        ]

        all_passed = True
        for label, check_func in checks:
            print(label)
            if not check_func():
                all_passed = False
            print()

        return all_passed

    def print_summary(self):
        """Mostrar resumen de errores y warnings."""
        print("\n" + "="*60)
        if self.errors:
            print("  ❌ ERRORES (DEBE CORREGIR)")
            print("="*60)
            for error in self.errors:
                print(f"  {error}")
            print()

        if self.warnings:
            print("  ⚠️ WARNINGS")
            print("="*60)
            for warning in self.warnings:
                print(f"  {warning}")
            print()

        if not self.errors and not self.warnings:
            print("  ✅ TODAS LAS VERIFICACIONES PASARON")
            print("="*60)
            print()

def push_to_github():
    """Hacer push a GitHub."""
    print("\n" + "="*60)
    print("  INICIANDO PUSH A GITHUB")
    print("="*60 + "\n")

    repo_root = Path(__file__).parent

    # Obtener rama actual
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(repo_root)
    )
    current_branch = result.stdout.strip()
    print(f"📌 Rama: {current_branch}")

    # Contar commits
    result = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        capture_output=True,
        text=True,
        cwd=str(repo_root)
    )
    last_commit = result.stdout.strip()
    print(f"📝 Último commit: {last_commit[:80]}")

    # Confirmar
    response = input("\n¿Confirmar push? (yes/no): ").strip().lower()
    if response != "yes":
        print("❌ Push cancelado")
        return False

    # Push
    print("\n⏳ Empujando cambios...\n")
    result = subprocess.run(
        ["git", "push", "origin", current_branch],
        cwd=str(repo_root)
    )

    if result.returncode == 0:
        print("\n✅ Push exitoso")
        print(f"   Repositorio: https://github.com/artoto45-ship-it/Interview-Copilot-Project")
        print(f"   Rama: {current_branch}")
        return True
    else:
        print("\n❌ Push fallido")
        return False

def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Safe GitHub Push Checker"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Solo ejecutar verificaciones"
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Verificar y hacer push"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Push sin verificación (use with caution!)"
    )

    args = parser.parse_args()

    if args.force:
        print("⚠️ MODO FUERZA — Saltando verificaciones\n")
        if push_to_github():
            sys.exit(0)
        else:
            sys.exit(1)

    # Modo normal: verificar primero
    checker = GitSafetyChecker()
    all_passed = checker.run_all_checks()
    checker.print_summary()

    if not all_passed:
        print("❌ Corrige los errores antes de hacer push")
        sys.exit(1)

    # Si --push, hacer push
    if args.push:
        if push_to_github():
            sys.exit(0)
        else:
            sys.exit(1)
    else:
        print("ℹ️ Ejecuta con --push para hacer push a GitHub")
        sys.exit(0)

if __name__ == "__main__":
    main()

