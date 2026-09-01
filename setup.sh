#!/bin/bash
# BLOCKORA_TRADE - Termux Setup Script

echo "=========================================="
echo "  BLOCKORA_TRADE Setup Script"
echo "  Platform: Android Termux"
echo "=========================================="
echo ""

echo "[1/6] Updating packages..."
pkg update -y && pkg upgrade -y

echo "[2/6] Installing Python..."
pkg install python -y

echo "[3/6] Installing system dependencies..."
pkg install git -y
pkg install libffi openssl -y

echo "[4/6] Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

echo "[5/6] Creating directories..."
mkdir -p logs database backup cache

echo "[6/6] Checking configuration..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  Created .env file - Please edit with your credentials"
else
    echo "  .env file already exists"
fi

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Edit .env file with your credentials"
echo "  2. Run: python main.py"
echo ""
