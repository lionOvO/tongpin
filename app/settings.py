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
        cookie_secure = os.getenv('SESSION_COOKIE_SECURE')
        if cookie_secure is not None and cookie_secure.lower() not in {'true', 'false'}:
            raise ValueError('SESSION_COOKIE_SECURE 必须为 true/false')
        self._session_cookie_secure = None if cookie_secure is None else cookie_secure.lower() == 'true'
        self.auto_seed = auto_seed if auto_seed is not None else os.getenv("AUTO_SEED", "false").lower() == "true"
        self.llm_mode = os.getenv("LLM_MODE", "demo")
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
        self.default_model_id = os.getenv('LLM_DEFAULT_MODEL_ID','deepseek')
        self.deepseek_pro_model = os.getenv('DEEPSEEK_PRO_MODEL','deepseek-v4-pro')
        self.deepseek_pro_input_price = float(os.getenv('DEEPSEEK_PRO_INPUT_PRICE_PER_MILLION','0'))
        self.deepseek_pro_output_price = float(os.getenv('DEEPSEEK_PRO_OUTPUT_PRICE_PER_MILLION','0'))
        self.relay_api_key = os.getenv('RELAY_API_KEY','')
        self.relay_base_url = os.getenv('RELAY_BASE_URL','https://api.sourcesdata.com/v1').rstrip('/')
        self.relay_model = os.getenv('RELAY_MODEL','gpt-5.6-sol')
        self.relay_sol_model = os.getenv('RELAY_SOL_MODEL','gpt-6.1-sol')
        self.relay_json_mode = os.getenv('RELAY_JSON_MODE','true').lower() == 'true'
        self.relay_stream = os.getenv('RELAY_RESPONSES_STREAM','true').lower() == 'true'
        self.relay_input_price = float(os.getenv('RELAY_INPUT_PRICE_PER_MILLION','0'))
        self.relay_output_price = float(os.getenv('RELAY_OUTPUT_PRICE_PER_MILLION','0'))
        self.model_profiles_json = os.getenv('LLM_PROFILES_JSON','[]')
        self.budget = float(os.getenv("COST_BUDGET_CNY", "50"))
        self.input_price = float(os.getenv("INPUT_PRICE_PER_MILLION", "2"))
        self.output_price = float(os.getenv("OUTPUT_PRICE_PER_MILLION", "3"))
        self.vector = os.getenv("VECTOR_ENABLED", "false").lower() == "true"
        # Same names as AI 漫剧; also accept 餐小助's backend variable names.
        self.sms = {name: os.getenv(name, os.getenv(alias, "")) for name, alias in {
            "ALIBABA_CLOUD_ACCESS_KEY_ID": "ALIYUN_ACCESS_KEY_ID",
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "ALIYUN_ACCESS_KEY_SECRET",
            "ALIBABA_SMS_SIGN_NAME": "ALIYUN_PNVS_SIGN_NAME",
            "ALIBABA_SMS_TEMPLATE_CODE": "ALIYUN_PNVS_TEMPLATE_CODE",
        }.items()}
        self.sms.update(region=os.getenv("ALIBABA_SMS_REGION", "cn-hangzhou"), scheme=os.getenv("ALIBABA_SMS_SCHEME_NAME", ""))

    @property
    def session_cookie_secure(self):
        return self.env == 'prod' if self._session_cookie_secure is None else self._session_cookie_secure
