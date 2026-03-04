#!/usr/bin/env python3
"""
Quick Verification Script for Interview Copilot v4.0
=====================================================
Verifica que el sistema está correctamente configurado y listo para ejecutar.
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Tuple


class SystemChecker:
    """Verifica requisitos del sistema y configuración"""

    def __init__(self):
        self.checks_passed = 0
        self.checks_failed = 0
        self.warnings = []
        self.root_dir = Path(__file__).parent

    def check(self, name: str, condition: bool, message: str = "") -> bool:
        """Realiza una verificación"""
        if condition:
            print(f"[OK]   {name}")
            self.checks_passed += 1
            return True
        else:
            print(f"[FAIL] {name}")
            if message:
                print(f"   -> {message}")
            self.checks_failed += 1
            return False

    def warn(self, message: str):
        """Registra una advertencia"""
        print(f"[WARN] {message}")
        self.warnings.append(message)

    def section(self, title: str):
        """Imprime un encabezado de sección"""
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")

    # ========================================================================
    # VERIFICACIONES
    # ========================================================================

    def check_python(self):
        """Verifica versión de Python"""
        self.section("REQUISITOS DE PYTHON")

        version = sys.version_info
        self.check(
            f"Python {version.major}.{version.minor}.{version.micro}",
            version.major >= 3 and version.minor >= 10,
            "Se requiere Python 3.10 o superior"
        )

    def check_dependencies(self):
        """Verifica dependencias instaladas"""
        self.section("DEPENDENCIAS")

        required = [
            ("websockets", "WebSocket para teleprompter"),
            ("openai", "API de OpenAI"),
            ("dotenv", "Variables de entorno"),
            ("numpy", "Computación numérica"),
        ]

        optional = [
            ("google.genai", "API de Gemini"),
            ("deepgram", "Transcripción Deepgram"),
            ("PyQt5", "UI del teleprompter"),
            ("prometheus_client", "Métricas Prometheus"),
            ("chromadb", "Base de datos vectorial"),
        ]

        print("\nDependencias Requeridas:")
        for package, description in required:
            try:
                __import__(package)
                self.check(f"{package:20s} ({description})", True)
            except ImportError:
                self.check(f"{package:20s} ({description})", False)

        print("\nDependencias Opcionales:")
        for package, description in optional:
            try:
                __import__(package)
                self.check(f"{package:20s} ({description})", True)
            except ImportError:
                self.warn(f"Opcional no instalado: {package}")

    def check_files(self):
        """Verifica estructura de archivos"""
        self.section("ESTRUCTURA DE ARCHIVOS")

        required_files = [
            "main.py",
            "requirements.txt",
            "README.md",
            ".gitignore",
        ]

        required_dirs = [
            "src",
            "src/audio",
            "src/transcription",
            "src/knowledge",
            "src/response",
            "src/teleprompter",
            "kb",
            "logs",
        ]

        print("\nArchivos Principales:")
        for f in required_files:
            path = self.root_dir / f
            self.check(f"{f:40s}", path.exists())

        print("\nDirectorios Principales:")
        for d in required_dirs:
            path = self.root_dir / d
            self.check(f"{d:40s}", path.is_dir())

    def check_environment(self):
        """Verifica variables de entorno"""
        self.section("VARIABLES DE ENTORNO")

        required_env = [
            ("OPENAI_API_KEY", "Clave API de OpenAI"),
        ]

        optional_env = [
            ("GOOGLE_API_KEY", "Clave API de Gemini"),
            ("DEEPGRAM_API_KEY", "Clave API de Deepgram"),
            ("OPENAI_ADMIN_KEY", "Clave Admin para saldo OpenAI live"),
            ("ANTHROPIC_ADMIN_KEY", "Clave Admin para saldo Anthropic live"),
            ("SALDO_BASELINE_START_UTC", "Baseline RFC3339 para saldo live"),
            ("VOICEMEETER_DEVICE_USER", "Dispositivo de audio del usuario"),
            ("VOICEMEETER_DEVICE_INT", "Dispositivo de audio del entrevistador"),
        ]

        # Intenta cargar .env
        try:
            from dotenv import load_dotenv
            load_dotenv(self.root_dir / ".env")
        except:
            self.warn("No se pudo cargar archivo .env")

        print("\nVariables Requeridas:")
        for var, description in required_env:
            value = os.getenv(var)
            self.check(
                f"{var:30s} ({description})",
                value is not None,
                "Configura en archivo .env"
            )
            if value:
                # Mostrar solo primeros caracteres por seguridad
                masked = value[:10] + "..." if len(value) > 10 else value
                print(f"   -> Valor: {masked}")

        print("\nVariables Opcionales:")
        for var, description in optional_env:
            value = os.getenv(var)
            if value:
                self.check(f"{var:30s} ({description})", True)
            else:
                self.warn(f"No configurada: {var}")

    def check_git(self):
        """Verifica configuración de git"""
        self.section("CONFIGURACIÓN GIT")

        try:
            import subprocess
            result = subprocess.run(
                ["git", "remote", "-v"],
                cwd=str(self.root_dir),
                capture_output=True,
                text=True
            )

            self.check(
                "Repositorio git inicializado",
                result.returncode == 0
            )

            if result.stdout:
                print("\nRemotos configurados:")
                for line in result.stdout.strip().split('\n'):
                    if line:
                        print(f"   -> {line}")

            # Verificar rama actual
            result_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(self.root_dir),
                capture_output=True,
                text=True
            )
            if result_branch.returncode == 0:
                branch = result_branch.stdout.strip()
                self.check(f"Rama actual: {branch}", True)

        except Exception as e:
            self.warn(f"No se pudo verificar git: {e}")

    def check_source_code(self):
        """Verifica integridad del código fuente"""
        self.section("INTEGRIDAD DEL CÓDIGO FUENTE")

        # Verificar que main.py tiene los módulos críticos
        try:
            with open(self.root_dir / "main.py", "r") as f:
                content = f.read()

            critical_imports = [
                "from src.audio.capture import AudioCaptureAgent",
                "from src.transcription.openai_realtime import OpenAIRealtimeTranscriber",
                "from src.knowledge.retrieval import KnowledgeRetriever",
                "from src.response.openai_agent import OpenAIAgent",
                "from src.response.fallback_manager import FallbackResponseManager",
                "from src.response.interview_memory import InterviewMemory",
            ]

            for import_stmt in critical_imports:
                module = import_stmt.split()[-1]
                self.check(f"Importa {module}", import_stmt in content)

        except Exception as e:
            self.warn(f"No se pudo verificar código fuente: {e}")

    def check_kb(self):
        """Verifica base de conocimientos"""
        self.section("BASE DE CONOCIMIENTOS (KB)")

        kb_dir = self.root_dir / "kb"
        if kb_dir.exists():
            # Contar archivos en KB
            personal_dir = kb_dir / "personal"
            company_dir = kb_dir / "company"

            personal_count = len(list(personal_dir.glob("*.txt"))) if personal_dir.exists() else 0
            company_count = len(list(company_dir.glob("*.txt"))) if company_dir.exists() else 0

            self.check(
                f"KB personal ({personal_count} archivos)",
                personal_count > 0,
                "Agrega archivos a kb/personal/"
            )

            self.check(
                f"KB empresarial ({company_count} archivos)",
                company_count > 0,
                "Agrega archivos a kb/company/"
            )
        else:
            self.warn("Directorio kb/ no encontrado")

    def check_ports(self):
        """Verifica puertos disponibles"""
        self.section("PUERTOS DISPONIBLES")

        import socket

        ports_to_check = [
            (8765, "WebSocket para teleprompter"),
            (8000, "Prometheus metrics"),
        ]

        for port, description in ports_to_check:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                result = sock.connect_ex(('127.0.0.1', port))
                is_available = result != 0
                self.check(
                    f"Puerto {port} disponible ({description})",
                    is_available,
                    f"Puerto {port} ya está en uso"
                )
            finally:
                sock.close()

    def generate_report(self):
        """Genera reporte final"""
        self.section("REPORTE FINAL")

        total = self.checks_passed + self.checks_failed
        percentage = (self.checks_passed / total * 100) if total > 0 else 0

        print(f"\n[OK]   Verificaciones pasadas: {self.checks_passed}")
        print(f"[INFO] Verificaciones fallidas: {self.checks_failed}")
        print(f"[INFO] Advertencias: {len(self.warnings)}")
        print(f"\nScore: {percentage:.1f}% ({self.checks_passed}/{total})")

        if self.checks_failed == 0 and len(self.warnings) <= 2:
            print("\nSISTEMA LISTO PARA EJECUTAR")
            return True
        elif self.checks_failed == 0:
            print("\nSISTEMA FUNCIONABLE (revisar advertencias)")
            return True
        else:
            print("\nSISTEMA NO LISTO (resolver errores)")
            return False

    def run_all_checks(self) -> bool:
        """Ejecuta todas las verificaciones"""
        print("\n")
        print("=" * 60)
        print("INTERVIEW COPILOT v4.0 - VERIFICACION DEL SISTEMA")
        print("=" * 60)

        self.check_python()
        self.check_dependencies()
        self.check_files()
        self.check_environment()
        self.check_git()
        self.check_source_code()
        self.check_kb()
        self.check_ports()

        return self.generate_report()


if __name__ == "__main__":
    checker = SystemChecker()
    success = checker.run_all_checks()

    print("\n" + "="*60)
    print("Para ejecutar el sistema:")
    print("  python main.py")
    print("\nPara más opciones:")
    print("  python main.py --help")
    print("="*60 + "\n")

    sys.exit(0 if success else 1)

