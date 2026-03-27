# Mock API server for testing RS sync
import json
from unittest.mock import Mock

class MockRSAPI:
    def __init__(self):
        # Тестовые данные для продуктов 61950 и 71650
        self.catalog_data = {
            "items": [
                {
                    "VENDOR_CODE": "61950",
                    "CODE": "100000001",
                    "NAME": "Test Product 61950"
                },
                {
                    "VENDOR_CODE": "71650",
                    "CODE": "100000002",
                    "NAME": "Test Product 71650"
                },
                {
                    "VENDOR_CODE": "12345",
                    "CODE": "100000003",
                    "NAME": "Test Product 12345"
                }
            ],
            "meta": {
                "last_page": 1,
                "rows_count": 3
            }
        }

        self.stock_data = {
            "residues": [
                {
                    "CODE": "100000001",
                    "RESIDUE": 25  # Для 61950
                },
                {
                    "CODE": "100000002",
                    "RESIDUE": 1097  # Для 71650
                },
                {
                    "CODE": "100000003",
                    "RESIDUE": 50  # Для 12345
                }
            ],
            "meta": {
                "last_page": 1
            }
        }

    def get_catalog_response(self, category="instock"):
        """Возвращает мок-ответ для каталога"""
        return self.catalog_data

    def get_stock_response(self):
        """Возвращает мок-ответ для остатков"""
        return self.stock_data
