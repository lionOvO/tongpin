"""Alibaba PNVS: codes are generated and verified remotely, never returned to clients."""
import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from .errors import DomainError


class AliyunSMS:
    def __init__(self, settings):
        self.settings = settings

    def missing(self):
        return [name for name in ("ALIBABA_CLOUD_ACCESS_KEY_ID", "ALIBABA_CLOUD_ACCESS_KEY_SECRET", "ALIBABA_SMS_SIGN_NAME", "ALIBABA_SMS_TEMPLATE_CODE") if not self.settings.sms.get(name)]

    def call(self, action, **fields):
        if self.missing():
            raise DomainError("SMS_NOT_CONFIGURED", "短信服务尚未配置，请联系管理员完成短信配置。", 503)
        cfg = self.settings.sms
        params = {"Action": action, "Version": "2017-05-25", "RegionId": cfg["region"], "CountryCode": "86", "Format": "JSON", "AccessKeyId": cfg["ALIBABA_CLOUD_ACCESS_KEY_ID"], "SignatureMethod": "HMAC-SHA1", "SignatureVersion": "1.0", "SignatureNonce": secrets.token_hex(16), "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **fields}
        if cfg["scheme"]:
            params["SchemeName"] = cfg["scheme"]
        encode = lambda value: quote(str(value), safe="~")
        canonical = "&".join(f"{encode(k)}={encode(params[k])}" for k in sorted(params))
        signed = "POST&%2F&" + encode(canonical)
        params["Signature"] = base64.b64encode(hmac.new((cfg["ALIBABA_CLOUD_ACCESS_KEY_SECRET"] + "&").encode(), signed.encode(), hashlib.sha1).digest()).decode()
        try:
            response = httpx.post("https://dypnsapi.aliyuncs.com/", data=params, timeout=10, follow_redirects=False)
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise DomainError("SMS_UNAVAILABLE", "短信服务暂不可用，请稍后重试。", 503) from None
        if not isinstance(payload, dict) or not isinstance(payload.get("Model", {}), dict):
            raise DomainError("SMS_UNAVAILABLE", "短信服务暂不可用，请稍后重试。", 503)
        if response.status_code != 200 or payload.get("Code") != "OK" or payload.get("Success") is False:
            code = payload.get("Code", "")
            message = "短信服务调用失败，请联系管理员检查权限、签名和模板。"
            status = 503
            if code in {"FREQUENCY_FAIL", "isv.BUSINESS_LIMIT_CONTROL"}:
                message, status = "验证码获取过于频繁，请稍后重试。", 429
            # Do not relay provider messages which may contain credentials or personal data.
            raise DomainError("SMS_PROVIDER_ERROR", message, status)
        return payload

    def send(self, phone):
        cfg = self.settings.sms
        result = self.call("SendSmsVerifyCode", PhoneNumber=phone, SignName=cfg["ALIBABA_SMS_SIGN_NAME"], TemplateCode=cfg["ALIBABA_SMS_TEMPLATE_CODE"], TemplateParam=json.dumps({"code": "##code##", "min": "5"}), CodeLength="6", CodeType="1", ValidTime="300", Interval="60", DuplicatePolicy="1", ReturnVerifyCode="false", AutoRetry="0", OutId="tongpin_" + secrets.token_hex(16))
        return (result.get("Model") or {}).get("BizId", "")

    def verify(self, phone, code):
        result = self.call("CheckSmsVerifyCode", PhoneNumber=phone, VerifyCode=code, CaseAuthPolicy="1")
        return (result.get("Model") or {}).get("VerifyResult") == "PASS"
