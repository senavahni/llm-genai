from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    """
    Application settings - loaded from .env file
    """
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore'
    )
    
    # ==================================================================
    # KONSTANTA - nilai tetap di kode, tidak perlu diisi di .env
    # ==================================================================
    APP_VERSION: str = "1.0.0"                # Versi aplikasi (tampil di docs & endpoint root)
    API_KEY_HEADER: str = "X-API-Key"         # Nama header HTTP untuk mengirim API key client
    DB_POOL_SIZE: int = 5                     # Jumlah koneksi DB yang selalu disiapkan di pool
    DB_MAX_OVERFLOW: int = 10                 # Koneksi tambahan di atas pool saat trafik tinggi
    RATE_LIMIT_ENABLED: bool = True           # Aktif/nonaktif rate limit (batas per client ada di tabel clients)

    # ==================================================================
    # DARI .env - bisa diubah per environment
    # ==================================================================

    # --- Application ---
    APP_NAME: str = "LLM Gateway"             # Nama aplikasi (judul docs & nama logger)
    DEBUG: bool = False                       # True = tampilkan detail error & log SQL. Matikan di produksi

    # --- Server ---
    HOST: str = "127.0.0.1"                   # Alamat bind server (127.0.0.1 = hanya lokal)
    PORT: int = 5000                          # Port server FastAPI
    PUBLIC_URL: str = "http://localhost:8080"  # URL publik lewat Traefik, dipakai membuat link file

    # --- Database (PostgreSQL Portable) ---
    # Format: postgresql+psycopg://user:password@host:port/nama_db
    DATABASE_URL: str = "postgresql+psycopg://user:password@localhost:5432/llm_gateway"
    
    # --- Storage ---
    STORAGE_PATH: str = "./storages"          # Folder penyimpanan file hasil (gambar disimpan di <STORAGE_PATH>/images)

    # --- Logging ---
    LOG_LEVEL: str = "INFO"                   # DEBUG / INFO / WARNING / ERROR
    LOG_FILE: Optional[str] = "./logs/app.log"  # File log; kosongkan untuk log ke console saja

    # --- Model lokal (folder model format OpenVINO IR di disk, dijalankan via optimum-intel) ---
    QWEN_TEXT_MODEL_PATH: str = "./models/modelllm/qwen2.5-7b-instruct-ov"        # Model teks umum
    QWEN_CODER_MODEL_PATH: str = "./models/modelllm/qwen2.5-coder-7b-instruct-ov"  # Model khusus coding
    QWEN_VISION_MODEL_PATH: str = "./models/modelllm/qwen2-vl-2b-instruct-ov"      # Model vision (baca gambar)
    STABLE_DIFFUSION_MODEL_PATH: str = "./models/modelllm/stable-diffusion-v1-5-ov"  # Model generate gambar

    # --- API key provider eksternal (opsional; kosong = provider tidak dipakai) ---
    # Ini key MILIK KAMU ke provider, bukan API key client gateway
    OPENAI_API_KEY: Optional[str] = None      # OpenAI
    CLAUDE_API_KEY: Optional[str] = None      # Anthropic Claude
    GEMINI_API_KEY: Optional[str] = None      # Google Gemini
    
    @property
    def storage_images_path(self) -> Path:
        """Get images storage path"""
        path = Path(self.STORAGE_PATH) / "images"
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    @property
    def logs_path(self) -> Path:
        """Get logs directory path"""
        path = Path("./logs")
        path.mkdir(parents=True, exist_ok=True)
        return path


# Global settings instance
settings = Settings()