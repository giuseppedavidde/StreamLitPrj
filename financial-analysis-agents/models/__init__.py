# models/__init__.py

from .data_schema import FinancialData

# Definisce cosa viene esportato quando qualcuno fa "from models import *"
__all__ = ["FinancialData"]