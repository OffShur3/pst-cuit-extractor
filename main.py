import sys
from pathlib import Path

# Asegurar que el directorio raíz esté en sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from src.ui.app import main

if __name__ == "__main__":
    main()
