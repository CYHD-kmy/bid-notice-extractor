"""Validated model configuration and non-generating Ollama preflight."""
from dataclasses import asdict, dataclass
import importlib.metadata
import json
import platform
from urllib.parse import urlsplit
from urllib.request import urlopen


@dataclass(frozen=True)
class RuntimeConfig:
    model: str = 'qwen3-vl:8b'
    model_url: str = 'http://127.0.0.1:11434'
    timeout_seconds: int = 55
    max_output_tokens: int = 1000
    num_ctx: int = 4096
    qwen_text_prefill: bool = True


def load_config(path=None):
    values = json.loads(path.read_text(encoding='utf-8')) if path else {}
    unknown=set(values)-set(RuntimeConfig.__dataclass_fields__)
    if unknown: raise ValueError('未知配置项：'+', '.join(sorted(unknown)))
    config=RuntimeConfig(**values)
    url=urlsplit(config.model_url)
    if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('模型地址必须是无凭据、查询或片段的HTTP(S)地址')
    if not isinstance(config.model,str) or not config.model.strip():raise ValueError('模型名不能为空')
    for key,lo,hi in [('timeout_seconds',1,300),('max_output_tokens',1,1000),('num_ctx',4096,32768)]:
        value=getattr(config,key)
        if type(value) is not int or not lo<=value<=hi:raise ValueError(f'{key}须为{lo}至{hi}的整数')
    if type(config.qwen_text_prefill) is not bool:raise ValueError('qwen_text_prefill须为布尔值')
    if config.qwen_text_prefill and config.model!='qwen3-vl:8b':
        raise ValueError('文本预填充仅适配原qwen3-vl:8b标签；其他模型请关闭并另行验证')
    return config


def preflight(config):
    base=config.model_url.rstrip('/')
    try:
        with urlopen(base+'/api/tags',timeout=min(config.timeout_seconds,5)) as response:
            tags=json.load(response)
        model=next((m for m in tags.get('models',[]) if m.get('name')==config.model or m.get('model')==config.model),None)
        if not model:raise ValueError('本地模型未安装：'+config.model+'；本程序不会自动下载')
        with urlopen(base+'/api/version',timeout=min(config.timeout_seconds,5)) as response:
            version=json.load(response)
        return {'name':config.model,'digest':model.get('digest'),'details':model.get('details'),
                'ollama_version':version.get('version')}
    except ValueError:raise
    except Exception as error:raise RuntimeError('无法连接模型服务，请检查地址和服务状态：'+str(error)) from error


def environment(config):
    packages={}
    for package in ('langextract','pdfplumber','pdfminer.six','pydantic'):
        try:packages[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:packages[package]=None
    return {'python':platform.python_version(),'platform':platform.system(),'architecture':platform.machine(),
            'packages':packages,'config':asdict(config)}
