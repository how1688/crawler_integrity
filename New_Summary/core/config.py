"""
配置檔案 - 新聞處理模組設定
"""

import os
from typing import Dict, Any

# 嘗試載入 .env 檔案
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))  # 載入 New_Summary 目錄的 .env 檔案
except ImportError:
    pass  # 如果沒有安裝 python-dotenv，跳過

class NewsProcessorConfig:
    """新聞處理器配置類"""
    
    # API 設定 - 使用類方法動態讀取
    @classmethod
    def get_gemini_api_key(cls):
        return os.getenv('GEMINI_API_KEY', '')
    GEMINI_MODEL = "gemini-2.5-flash-lite"
    
    # Supabase 設定
    @classmethod
    def get_supabase_url(cls):
        return os.getenv('SUPABASE_URL', '')
    
    @classmethod
    def get_supabase_key(cls):
        return os.getenv('SUPABASE_KEY', '')
    
    # 處理參數
    BATCH_SIZE = 5  # 每次處理幾個 stories 後保存進度
    API_DELAY = 1  # API 調用間隔秒數
    MAX_CONTENT_LENGTH = 2000  # 文章內容最大長度（避免超過 token 限制）
    
    # Gemini 生成參數
    GENERATION_CONFIGS = {
        "analysis": {
            "temperature": 0.3,
            "max_output_tokens": 800,
            "top_p": 0.8,
            "top_k": 25
        },
        "short_summary": {
            "temperature": 0.2,
            "max_output_tokens": 200,
            "top_p": 0.7,
            "top_k": 20
        },
        "medium_summary": {
            "temperature": 0.3,
            "max_output_tokens": 600,
            "top_p": 0.8,
            "top_k": 25
        },
        "long_summary": {
            "temperature": 0.4,
            "max_output_tokens": 1200,
            "top_p": 0.9,
            "top_k": 30
        }
    }
    
    # 安全設置
    SAFETY_SETTINGS = [
        {
            "category": "HARM_CATEGORY_HARASSMENT", # 性騷擾
            "threshold": "BLOCK_MEDIUM_AND_ABOVE" # 中度及更高
        },
        {
            "category": "HARM_CATEGORY_HATE_SPEECH", # 仇恨言論
            "threshold": "BLOCK_MEDIUM_AND_ABOVE" # 中度及更高
        },
        {
            "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", # 性暗示
            "threshold": "BLOCK_MEDIUM_AND_ABOVE" # 中度及更高
        },
        {
            "category": "HARM_CATEGORY_DANGEROUS_CONTENT", # 危險內容
            "threshold": "BLOCK_MEDIUM_AND_ABOVE" # 中度及更高
        }
    ]

    @classmethod
    def validate_config(cls) -> bool:
        """驗證配置是否正確"""
        if not cls.get_gemini_api_key():
            print("錯誤: GEMINI_API_KEY 未設定")
            print("請設定環境變數或在 config.py 中直接設定")
            return False
        
        if not cls.get_supabase_url() or not cls.get_supabase_key():
            print("錯誤: SUPABASE_URL 或 SUPABASE_KEY 未設定")
            print("請設定環境變數")
            return False
        return True
