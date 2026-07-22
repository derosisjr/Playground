import os
import sys

# os módulos do pacote vivem em despesas/ e se importam entre si sem pacote
# (`import export`), então o diretório precisa estar no path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
