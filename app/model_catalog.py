"""Server-owned model profiles; clients select an ID, never a URL or credential."""
import json
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from .errors import DomainError


@dataclass(frozen=True)
class ModelProfile:
    id: str
    label: str
    provider: str
    model: str
    protocol: str
    base_url: str
    api_key: str = field(repr=False)
    input_price: float = 0
    output_price: float = 0
    json_mode: bool = True
    stream: bool = False
    deepseek_thinking: bool = False
    external: bool = False

    def public(self, enabled=True):
        return {"id": self.id, "label": self.label, "provider": self.provider,
            "model": self.model, "protocol": self.protocol, "external": self.external,
            "available": enabled and bool(self.api_key),
            "unavailable_reason": "" if enabled and self.api_key else "AI 服务未启用" if not enabled else "服务器尚未配置该服务的密钥"}

    def provenance(self):
        return {"model_id": self.id, "model_label": self.label, "provider": self.provider,
            "model": self.model, "protocol": self.protocol}


class ModelCatalog:
    def __init__(self, settings):
        self.settings = settings
        try:
            self.extra = json.loads(getattr(settings, 'model_profiles_json', '[]'))
            if not isinstance(self.extra, list) or len(self.extra) > 20:
                raise ValueError()
            for item in self.extra:
                self.validate_extra(item)
            ids = [item['id'] for item in self.extra]
            if len(set(ids)) != len(ids) or set(ids) & {'deepseek', 'deepseek-pro', 'relay-gpt', 'relay-gpt-61'}:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise ValueError('LLM_PROFILES_JSON 配置无效，请检查模型 ID、接口地址和密钥变量名') from None
        if getattr(settings, 'default_model_id', 'deepseek') not in {p.id for p in self.profiles()}:
            raise ValueError('LLM_DEFAULT_MODEL_ID 不在服务器模型列表中')

    @property
    def enabled(self):
        return self.settings.llm_mode in {'deepseek', 'live'}

    @property
    def default_id(self):
        return getattr(self.settings, 'default_model_id', 'deepseek')

    @staticmethod
    def validate_url(url):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('模型地址必须为不含凭据的 HTTPS API 基址')

    @classmethod
    def validate_extra(cls, item):
        allowed = {'id','label','provider','model','protocol','base_url','api_key_env','input_price','output_price','json_mode','stream'}
        if not isinstance(item, dict) or set(item) - allowed:
            raise ValueError()
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', item['id']):
            raise ValueError()
        for key, limit in [('label',100),('provider',100),('model',150)]:
            if not isinstance(item[key],str) or not item[key].strip() or len(item[key]) > limit:
                raise ValueError()
        if item['protocol'] not in {'chat_completions','responses'} or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}', item['api_key_env']):
            raise ValueError()
        cls.validate_url(item['base_url'])
        for key in ('input_price','output_price'):
            if not isinstance(item.get(key,0),(int,float)) or not 0 <= item.get(key,0) <= 100000:
                raise ValueError()
        if any(key in item and not isinstance(item[key],bool) for key in ('json_mode','stream')):
            raise ValueError()

    def profiles(self):
        s = self.settings
        profiles = [
            ModelProfile('deepseek', 'DeepSeek Flash', 'DeepSeek 官方', s.model, 'chat_completions', s.base_url, s.api_key,
                s.input_price, s.output_price, deepseek_thinking=s.model.startswith(('deepseek-flash','deepseek-v4'))),
            ModelProfile('deepseek-pro', 'DeepSeek Pro', 'DeepSeek 官方', getattr(s,'deepseek_pro_model','deepseek-v4-pro'),
                'chat_completions', s.base_url, s.api_key, getattr(s,'deepseek_pro_input_price',0), getattr(s,'deepseek_pro_output_price',0), deepseek_thinking=True),
        ]
        relay_base = getattr(s, 'relay_base_url', 'https://api.sourcesdata.com/v1').rstrip('/')
        # The discussed relay URL is an origin; the OpenAI API prefix is /v1.
        if not urlsplit(relay_base).path:
            relay_base += '/v1'
        for id, label, model in [('relay-gpt','GPT 5.6 Sol · 中转站',getattr(s,'relay_model','gpt-5.6-sol')),
                                 ('relay-gpt-61','GPT 6.1 Sol · 中转站',getattr(s,'relay_sol_model','gpt-6.1-sol'))]:
            profiles.append(ModelProfile(id,label,'SourcesData 中转站',model,'responses',relay_base,getattr(s,'relay_api_key',''),
                getattr(s,'relay_input_price',0),getattr(s,'relay_output_price',0),getattr(s,'relay_json_mode',True),getattr(s,'relay_stream',False),external=True))
        for p in self.extra:
            profiles.append(ModelProfile(p['id'],p['label'],p['provider'],p['model'],p['protocol'],p['base_url'].rstrip('/'),os.getenv(p['api_key_env'],''),
                p.get('input_price',0),p.get('output_price',0),p.get('json_mode',True),p.get('stream',False),external=True))
        return profiles

    def resolve(self, id=None, require_ready=False):
        profile = next((p for p in self.profiles() if p.id == (id or self.default_id)), None)
        if not profile:
            raise DomainError('AI_MODEL_UNKNOWN','所选模型不在服务器允许的列表中，请刷新模型列表。',422)
        if require_ready and (not self.enabled or not profile.api_key):
            raise DomainError('AI_NOT_CONFIGURED','所选模型尚未启用或未配置密钥，请选择可用模型。',503)
        return profile

    def public(self):
        return {'default_model_id':self.default_id,'models':[p.public(self.enabled) for p in self.profiles()]}
