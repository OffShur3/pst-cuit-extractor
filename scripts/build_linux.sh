#!/usr/bin/env bash
set -e

echo "============================================="
echo "🧹 Limpiando compilaciones anteriores..."
echo "============================================="
rm -rf build dist *.spec

echo "============================================="
echo "🔨 Compilando ejecutable para Linux..."
echo "============================================="
pyinstaller --noconsole --onefile --clean \
    --name "pst-cuit-extractor" \
    --collect-all customtkinter \
    --collect-all PIL \
    --hidden-import PIL._tkinter_finder \
    --collect-all openpyxl \
    main.py

echo ""
echo "============================================="
echo "✅ Compilación finalizada con éxito."
echo "👉 Ejecutable generado en: dist/pst-cuit-extractor"
echo "============================================="
