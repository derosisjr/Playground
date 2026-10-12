import os
import sys

# os módulos vivem em legis/ e se importam sem pacote (`from revogacoes import ...`)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
