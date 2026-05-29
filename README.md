# AI Travel Planner Demo

一个基于 Python 的命令行 AI 旅行推荐助手。项目使用大语言模型驱动 ReAct-style agent loop，根据用户输入、实时天气、用户偏好、预算和景点门票可用性信号，生成更贴合场景的旅行景点推荐。

## Project Status

- 当前状态: 本地可运行 demo / prototype
- 运行方式: 命令行脚本
- 部署状态: 尚未部署上线
- 数据存储: 本地 JSON 文件保存用户偏好
- 适合用途: 简历项目、AI Agent 练习项目、旅行推荐系统原型

## Features

- 根据用户输入的城市和需求生成旅行推荐
- 查询实时天气，并结合天气选择更合适的景点
- 使用 Tavily Search API 搜索景点推荐和门票可用性信息
- 通过 OpenAI 或 OpenAI-compatible API 驱动智能推理
- 自动记录用户偏好，例如历史文化、自然风光、亲子、美食、室内活动
- 记录预算信息，并在推荐时作为参考
- 记录用户拒绝过的推荐，避免重复推荐类似景点
- 当用户连续拒绝多个推荐时，自动反思并调整推荐策略

## Tech Stack

- Python 3.10+
- OpenAI Python SDK
- Tavily Search API
- wttr.in Weather API
- requests
- python-dotenv
- JSON local storage

## Project Structure

```text
.
├── agent.py           # Main AI travel planner agent
├── .env.example       # Example environment variables
├── .gitignore         # Ignored local files
├── requirements.txt   # Python dependencies
└── README.md          # Project documentation
```

`user_memory.json` is generated locally at runtime and is ignored by Git because it stores user-specific preferences.

## Setup

1. Create and activate a virtual environment.

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Create a `.env` file from the example.

```bash
cp .env.example .env
```

4. Fill in the required API keys.

```env
OPENAI_API_KEY=your_openai_api_key_here
TAVILY_API_KEY=your_tavily_api_key_here
MODEL_ID=gpt-4o-mini
BASE_URL=https://api.openai.com/v1
```

## Usage

Run with the default demo prompt:

```bash
python agent.py
```

Run with a custom travel request:

```bash
python agent.py "我想去北京，预算150元，喜欢历史文化和室内活动，请根据今天的天气推荐一个景点"
```

The agent will repeatedly produce:

```text
Thought: ...
Action: ...
Observation: ...
```

When enough information has been gathered, it finishes with a final recommendation.

## Resume Summary

Developed a Python-based AI travel planning assistant that uses OpenAI-compatible LLM APIs, Tavily Search, and real-time weather data to recommend attractions based on user preferences, budget, and ticket availability signals. Implemented a ReAct-style agent loop, local user memory, preference tracking, rejection handling, and adaptive recommendation strategy.

## Notes

This is currently a command-line prototype rather than a deployed web application. A production version could add a web UI, persistent database, official ticketing integrations, tests, and cloud deployment.
