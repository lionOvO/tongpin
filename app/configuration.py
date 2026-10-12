import json
import re
import threading
from pathlib import Path
from .settings import ROOT
from .errors import DomainError

CONFIG_NAMES = {"rubric":"rubric.json", "priorities":"priority_templates.json", "preferences":"preference_dimensions.json", "major-map":"major_domain_map.json", "presentation":"presentation.json"}


class Configuration:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "config"
        self.path.mkdir(exist_ok=True)
        self.lock = threading.RLock()

    def get(self, name):
        if name not in CONFIG_NAMES:
            raise DomainError("CONFIG_UNKNOWN", "配置不存在", 404)
        path = self.path / CONFIG_NAMES[name]
        with self.lock:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            active = self.path / "active_pack.json"
            if active.exists():
                return json.loads(active.read_text(encoding="utf-8"))["configs"][name]
            return json.loads((ROOT / "config" / CONFIG_NAMES[name]).read_text(encoding="utf-8"))

    def validate(self, name, data):
        if not isinstance(data, dict) or not isinstance(data.get("version"), str) or not data["version"].strip():
            raise DomainError("CONFIG_INVALID", "配置必须包含非空版本号")
        if name == "priorities":
            p, enabled = data.get("priorities", {}), data.get("enabled", [])
            if not isinstance(p,dict) or not isinstance(enabled,list) or any(not isinstance(d,str) for d in enabled):
                raise DomainError("PRIORITY_INVALID", "优先级须为对象，启用维度须为字符串列表")
            if not enabled or len(enabled) != len(set(enabled)) or set(enabled) - {"D1","D2","D3","D4","D5"} or any(p.get(d) not in {"P0","P1","P2"} for d in enabled) or not any(p[d] == "P0" for d in enabled):
                raise DomainError("PRIORITY_INVALID", "启用维度必须唯一、均有有效优先级，且至少一个核心维度")
        if name == "preferences":
            dims = data.get("dimensions", [])
            if not isinstance(dims,list) or len(dims)!=8 or any(not isinstance(d,dict) or not isinstance(d.get("id"),str) or not isinstance(d.get("name"),str) or not isinstance(d.get("required"),bool) or not isinstance(d.get("options"),list) or any(not isinstance(v,str) or not v for v in d["options"]) for d in dims):
                raise DomainError("PREFERENCE_CONFIG_INVALID", "须提供八项完整偏好维度及有效选项")
            if len({d.get("id") for d in dims}) != len(dims) or sum(bool(d.get("required")) for d in dims) != 3 or not all(d.get("options") and len(set(d["options"])) == len(d["options"]) for d in dims):
                raise DomainError("PREFERENCE_CONFIG_INVALID", "偏好维度必须唯一、恰有三项必填，并提供不重复的选项")
            if {d["id"] for d in dims if d["required"]} != {"direction","autonomy","learning"}:
                raise DomainError("REQUIRED_DIMENSIONS", "三项必填固定为技术方向、自主性、学习与成长")
            pairs=data.get("related_directions",[])
            directions=next(d["options"] for d in dims if d["id"]=="direction")
            if not isinstance(pairs,list) or any(not isinstance(p,list) or len(p)!=2 or any(v not in directions for v in p) for p in pairs):
                raise DomainError("PREFERENCE_CONFIG_INVALID", "关联方向须引用现有方向选项")
        if name == "presentation":
            for key in ["bias_notice","footer"]:
                if not isinstance(data.get(key),str): raise DomainError("PRESENTATION_INVALID", "提示语须为文本")
            for key in ["banned_terms","enterprise_banned_terms"]:
                if not isinstance(data.get(key),list) or any(not isinstance(v,str) or not v for v in data[key]): raise DomainError("PRESENTATION_INVALID", "禁词须为非空文本列表")
            for key in ["tier_labels","preference_labels"]:
                if not isinstance(data.get(key),dict) or any(not isinstance(v,str) or not v for v in data[key].values()): raise DomainError("PRESENTATION_INVALID", "关系映射须为非空文本对象")
            if any(any(term not in data.get(key, '') for term in ('可能存在偏差', '系统不设合格线')) for key in ('bias_notice', 'footer')):
                raise DomainError("NOTICE_REQUIRED", "提示须包含可能存在偏差与不设合格线")
            if not set(self.get(name)["banned_terms"]).issubset(data.get("banned_terms", [])) or not set(self.get(name)["enterprise_banned_terms"]).issubset(data.get("enterprise_banned_terms", [])):
                raise DomainError("PRESENTATION_INVALID", "不得移除已有呈现禁词")
            if set(data.get("tier_labels",{}))!={"B1","B2","B3","B4","B5","insufficient"} or set(data.get("preference_labels",{}))!={"高","中","低","无法判断"}:
                raise DomainError("PRESENTATION_INVALID","呈现映射必须包含完整关系")
            text = json.dumps([list(data.get("tier_labels", {}).values()),list(data.get("preference_labels", {}).values())], ensure_ascii=False)
            if any(t in text for t in data["banned_terms"] + data["enterprise_banned_terms"]) or re.search(r"\d\s*%", text):
                raise DomainError("PRESENTATION_INVALID", "结果措辞包含禁止表达")
        if name == "rubric":
            for key,expected in [("dimensions",{"D1","D2","D3","D4","D5"}),("skill_anchors",{"0","1","2","3","4"})]:
                value=data.get(key)
                if not isinstance(value,dict) or set(value)!=expected or any(not isinstance(v,str) or not v for v in value.values()): raise DomainError("RUBRIC_INVALID", "量规须提供完整维度与技能行为锚点")
            anchors=data.get("anchors")
            if not isinstance(data.get("status"),str) or not isinstance(anchors,dict) or not {"D1","D2","D3","D5"}.issubset(anchors) or any(not isinstance(value,dict) or not value or set(value)-{"B1","B2","B3","B4","B5"} or any(not isinstance(v,str) or not v for v in value.values()) for value in anchors.values()):
                raise DomainError("RUBRIC_INVALID", "量规维度锚点或状态无效")
            if data.get('d2_percentile_thresholds') != {'B5':90, 'B4':75, 'B3':60, 'B2':40, 'B1':0}:
                raise DomainError('RUBRIC_INVALID', '成绩分界必须与上游量规一致')
            if set(anchors) != {'D1', 'D2', 'D3', 'D4', 'D5'} or any(set(value) != {'B1', 'B2', 'B3', 'B4', 'B5'} for value in anchors.values()):
                raise DomainError('RUBRIC_INVALID', '五个维度必须提供全部五档锚点')
            insufficient = data.get('insufficient_anchors')
            disciplines = data.get('general_disciplines')
            if not isinstance(insufficient, dict) or set(insufficient) != set(anchors) or not isinstance(disciplines, list) or len(disciplines) != 8 or any(not isinstance(value,str) or not value for value in disciplines):
                raise DomainError('RUBRIC_INVALID', '须保留全部证据不足说明与八条通用纪律')
            requirements = data.get('evidence_requirements')
            if not isinstance(requirements, dict) or set(requirements) != set(anchors) or any(not isinstance(rows,dict) or set(rows)!=set(anchors[dimension]) for dimension,rows in requirements.items()):
                raise DomainError('RUBRIC_INVALID', '须提供完整的逐档证据要求对象')
            for dimension, rows in anchors.items():
                for tier, anchor in rows.items():
                    requirement = requirements[dimension][tier]
                    if not isinstance(requirement, dict) or any(not isinstance(requirement.get(k), str) or not requirement[k] for k in ('original','requirement')) or requirement.get('requirement')=='同上':
                        raise DomainError('RUBRIC_INVALID', '每档须提供可独立读取的证据要求')
                    if re.search(r'同上|分数|得分|评分|±', anchor) or any(t != tier for t in re.findall(r'B[1-5]', anchor)):
                        raise DomainError('RUBRIC_INVALID', '锚点不得含分数或依赖其他档位')
        if name == "major-map" and not isinstance(data.get("related"), list):
            raise DomainError("MAJOR_MAP_INVALID", "专业映射必须提供 related 列表")

    def save(self, name, data):
        self.get(name)
        with self.lock:
            self.validate(name, data)
            if data["version"] == self.get(name)["version"]:
                raise DomainError("VERSION_REQUIRED", "修改配置须使用新的版本号，历史结果不会静默重算")
            target = self.path / CONFIG_NAMES[name]
            temp = target.with_suffix(".tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(target)
        return data

    def pack(self):
        with self.lock:
            active=self.path / "active_pack.json"
            version=json.loads(active.read_text(encoding="utf-8"))["pack_version"] if active.exists() else "pack-draft-0.1"
            return {"pack_version":version, "configs":{k:self.get(k) for k in CONFIG_NAMES}}

    def import_pack(self, data):
        configs = data.get("configs", {})
        if set(configs) != set(CONFIG_NAMES) or not data.get("pack_version"):
            raise DomainError("PACK_INVALID", "标准包须包含完整配置和版本号")
        with self.lock:
            for name, value in configs.items():
                self.validate(name, value)
                if (self.path / CONFIG_NAMES[name]).exists():
                    raise DomainError("PACK_OVERRIDE_EXISTS", "已有独立配置修订，请使用配置页逐项更新或在新环境导入标准包")
            # Single atomic manifest switch prevents partially imported packs.
            target = self.path / "active_pack.json"
            temp = target.with_suffix(".tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(target)
        return data
