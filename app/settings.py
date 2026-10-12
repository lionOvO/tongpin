import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


class Settings:
    def __init__(self, data_dir=None, env=None, auto_seed=None):
        self.data_dir = Path(data_dir or os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()
        self.env = env or os.getenv("APP_ENV", "demo")
        if self.env not in {"dev", "demo", "prod"}:
            raise ValueError("APP_ENV 必须为 dev/demo/prod")
        self.auto_seed = auto_seed if auto_seed is not None else os.getenv("AUTO_SEED", "true").lower() == "true"
        self.llm_mode = os.getenv("LLM_MODE", "demo")
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.budget = float(os.getenv("COST_BUDGET_CNY", "50"))
        self.input_price = float(os.getenv("INPUT_PRICE_PER_MILLION", "2"))
        self.output_price = float(os.getenv("OUTPUT_PRICE_PER_MILLION", "3"))
        self.vector = os.getenv("VECTOR_ENABLED", "false").lower() == "true"

