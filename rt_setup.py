#!/usr/bin/env python3
"""
rt_setup.py - Wrapper di retrocompatibilità per il modulo nativo rt.pipeline.setup.
Consente l'esecuzione trasparente dello script standalone mantenendo piena compatibilità CLI.
"""
import sys
import os

# Assicura che la root del progetto sia in sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from rt.pipeline.setup import main

if __name__ == "__main__":
    main()
