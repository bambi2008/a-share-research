#!/usr/bin/env python3
"""
LLM 客户端 - provider 无关(OpenAI 兼容接口)
支持 DeepSeek / 通义千问 / OpenAI / 月之暗面 等所有 OpenAI 兼容服务。

配置文件 config.json (与本脚本同目录):
{
  "api_key": "sk-xxxx",
  "base_url": "https://api.deepseek.com/v1",
  "model": "deepseek-chat"
}
"""
import json
import os
import urllib.request


# 常见 provider 预设
PRESETS = {
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o"},
    "moonshot": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
}

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
}


def config_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    """读取配置。不存在则创建模板并返回默认。"""
    path = config_path()
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        return DEFAULT_CONFIG.copy()
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    # 补全缺失字段
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(api_key=None, base_url=None, model=None, preset=None):
    cfg = load_config()
    if preset and preset in PRESETS:
        cfg["base_url"] = PRESETS[preset]["base_url"]
        cfg["model"] = PRESETS[preset]["model"]
    if api_key is not None:
        cfg["api_key"] = api_key
    if base_url is not None:
        cfg["base_url"] = base_url
    if model is not None:
        cfg["model"] = model
    with open(config_path(), 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


def is_configured():
    cfg = load_config()
    return bool(cfg.get("api_key"))


def chat(messages, temperature=0.4, max_tokens=2000, timeout=120):
    """调用 LLM。messages: [{"role":"user","content":"..."}]
    返回回复文本。未配置 key 抛 RuntimeError。
    """
    cfg = load_config()
    if not cfg.get("api_key"):
        raise RuntimeError("未配置 API key，请在 config.json 填写 api_key")

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result["choices"][0]["message"]["content"]


if __name__ == "__main__":
    print(f"配置文件: {config_path()}")
    cfg = load_config()
    print(f"base_url: {cfg['base_url']}")
    print(f"model: {cfg['model']}")
    print(f"已配置key: {is_configured()}")
    if is_configured():
        print("\n测试调用...")
        try:
            reply = chat([{"role": "user", "content": "用一句话确认你能正常工作"}])
            print(f"回复: {reply}")
        except Exception as e:
            print(f"调用失败: {e}")
    else:
        print("\n请在 config.json 填写 api_key 后重试")
