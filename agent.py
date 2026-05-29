import requests
import os
import json
import sys
from dotenv import load_dotenv
load_dotenv(override=True)
from tavily import TavilyClient
from openai import OpenAI
import re
from pathlib import Path


AGENT_SYSTEM_PROMPT = """
你是一个智能旅行助手。你的任务是分析用户的请求，并使用可用工具一步步地解决问题。

# 可用工具：
- `get_weather(city: str)`: 查询指定城市的实时天气。
- `get_attraction(city: str, weather: str)`: 根据城市、天气、用户记忆和当前策略搜索推荐的旅游景点。
- `check_ticket_availability(attraction: str, city: str)`: 检查推荐景点门票是否可能售罄。
- `remember_user_preference(preferences: str, budget: str)`: 记录用户偏好和预算。
- `record_rejection(attraction: str, reason: str)`: 记录用户拒绝某个推荐。
- `reflect_recommendation_strategy()`: 当用户连续拒绝3个推荐后，反思并调整推荐策略。

# 输出格式要求：
你的每次回复必须严格遵循以下格式，包含一对Thought和Action:

Thought: [你的思考过程和下一步计划]
Action: [你要执行的具体行动]

Action的格式必须是以下之一：
1. 调用工具：function_name(arg_name="arg_value")
2. 结束任务：Finish[最终答案]

# 重要提示：
- 每次只输出一对Thought-Action
- Action必须在同一行，不要换行
- 当收集到足够信息可以回答用户问题时，必须使用 Action: Finish[最终答案] 格式结束
- 推荐景点前要参考用户记忆。get_attraction 返回候选后，应调用 check_ticket_availability 检查门票。
- 如果发现门票售罄，必须继续调用 get_attraction 寻找备选方案。
- 如果用户连续拒绝了3个推荐，必须先调用 reflect_recommendation_strategy()，再继续推荐。

请开始吧！
"""


MEMORY_FILE = Path("user_memory.json")


def default_memory() -> dict:
    return {
        "preferences": [],
        "budget": "",
        "rejected_recommendations": [],
        "consecutive_rejections": 0,
        "strategy_note": "",
    }


def load_user_memory() -> dict:
    if not MEMORY_FILE.exists():
        return default_memory()

    try:
        with MEMORY_FILE.open("r", encoding="utf-8") as file:
            memory = json.load(file)
    except (json.JSONDecodeError, OSError):
        return default_memory()

    merged = default_memory()
    merged.update(memory)
    return merged


def save_user_memory(memory: dict) -> None:
    with MEMORY_FILE.open("w", encoding="utf-8") as file:
        json.dump(memory, file, ensure_ascii=False, indent=2)


def format_user_memory(memory: dict) -> str:
    preferences = "、".join(memory.get("preferences", [])) or "暂无"
    budget = memory.get("budget") or "暂无"
    rejected = "、".join(item["attraction"] for item in memory.get("rejected_recommendations", [])[-5:]) or "暂无"
    strategy_note = memory.get("strategy_note") or "暂无"

    return (
        "用户记忆:\n"
        f"- 偏好: {preferences}\n"
        f"- 预算: {budget}\n"
        f"- 连续拒绝次数: {memory.get('consecutive_rejections', 0)}\n"
        f"- 最近拒绝过的推荐: {rejected}\n"
        f"- 当前推荐策略: {strategy_note}"
    )


def auto_capture_preferences(user_text: str) -> None:
    """
    用简单规则从用户输入里提取偏好，避免每次都依赖模型先调用记忆工具。
    """
    memory = load_user_memory()
    preference_keywords = {
        "历史文化": ["历史", "文化", "博物馆", "古迹", "故宫", "寺庙"],
        "自然风光": ["自然", "风景", "山", "湖", "公园", "徒步"],
        "亲子友好": ["亲子", "孩子", "儿童", "家庭"],
        "美食体验": ["美食", "小吃", "餐厅"],
        "室内活动": ["室内", "下雨", "避雨"],
    }

    for preference, keywords in preference_keywords.items():
        if any(keyword in user_text for keyword in keywords) and preference not in memory["preferences"]:
            memory["preferences"].append(preference)

    budget_match = re.search(r"(预算|人均|门票|花费)[^\d]*(\d+)\s*(元|块|人民币)?", user_text)
    if budget_match:
        memory["budget"] = f"{budget_match.group(2)}元左右"

    save_user_memory(memory)


def get_weather(city: str) -> str:
    """
    通过调用 wttr.in API 查询真实的天气信息。
    """
    url = f"https://wttr.in/{city}?format=j1"

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        current_condition = data["current_condition"][0]
        weather_desc = current_condition["weatherDesc"][0]["value"]
        temp_c = current_condition["temp_C"]

        return f"{city}当前天气:{weather_desc}，气温{temp_c}摄氏度"

    except requests.exceptions.RequestException as e:
        return f"错误:查询天气时遇到网络问题 - {e}"
    except (KeyError, IndexError) as e:
        return f"错误:解析天气数据失败，可能是城市名称无效 - {e}"
    



def get_attraction(city: str, weather: str) -> str:
    """
    根据城市、天气和用户记忆，使用Tavily Search API搜索并返回优化后的景点推荐。
    """
    # 1. 从环境变量中读取API密钥
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return "错误:未配置TAVILY_API_KEY环境变量。"

    # 2. 初始化Tavily客户端
    tavily = TavilyClient(api_key=api_key)
    
    memory = load_user_memory()
    excluded = "、".join(item["attraction"] for item in memory.get("rejected_recommendations", [])[-5:])
    preferences = "、".join(memory.get("preferences", [])) or "无明确偏好"
    budget = memory.get("budget") or "无明确预算"
    strategy_note = memory.get("strategy_note") or "优先匹配天气、用户偏好和交通便利性"

    query = (
        f"'{city}' 在'{weather}'天气下最值得去的旅游景点推荐及理由。"
        f"用户偏好:{preferences}; 预算:{budget}; 当前策略:{strategy_note};"
        f"避开这些用户拒绝过的景点:{excluded or '无'}。"
        "请优先返回仍可预约或容易买票的方案。"
    )
    
    try:
        # 4. 调用API，include_answer=True会返回一个综合性的回答
        response = tavily.search(query=query, search_depth="basic", include_answer=True)
        
        # 5. Tavily返回的结果已经非常干净，可以直接使用
        # response['answer'] 是一个基于所有搜索结果的总结性回答
        if response.get("answer"):
            return response["answer"]
        
        # 如果没有综合性回答，则格式化原始结果
        formatted_results = []
        for result in response.get("results", []):
            formatted_results.append(f"- {result['title']}: {result['content']}")
        
        if not formatted_results:
             return "抱歉，没有找到相关的旅游景点推荐。"

        return "根据搜索，为您找到以下信息:\n" + "\n".join(formatted_results)

    except Exception as e:
        return f"错误:执行Tavily搜索时出现问题 - {e}"


def check_ticket_availability(attraction: str, city: str) -> str:
    """
    通过搜索公开信息判断门票是否可能售罄。真实生产系统应接官方票务API。
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return "错误:未配置TAVILY_API_KEY环境变量。"

    tavily = TavilyClient(api_key=api_key)
    query = f"{city} {attraction} 今日 门票 售罄 约满 无票 预约"

    try:
        response = tavily.search(query=query, search_depth="basic", include_answer=True)
    except Exception as e:
        return f"错误:检查门票状态时出现问题 - {e}"

    text = response.get("answer") or " ".join(result.get("content", "") for result in response.get("results", []))
    sold_out_keywords = ["售罄", "约满", "无票", "已满", "暂停预约", "不可预约"]
    if any(keyword in text for keyword in sold_out_keywords):
        return f"{attraction} 的门票可能已售罄或预约已满，请自动推荐备选方案。搜索摘要:{text[:300]}"

    return f"未发现 {attraction} 明确售罄信号，但仍建议用户出行前到官方渠道确认。搜索摘要:{text[:300]}"


def remember_user_preference(preferences: str, budget: str = "") -> str:
    memory = load_user_memory()

    for preference in re.split(r"[，,、\s]+", preferences):
        preference = preference.strip()
        if preference and preference not in memory["preferences"]:
            memory["preferences"].append(preference)

    if budget:
        memory["budget"] = budget

    save_user_memory(memory)
    return format_user_memory(memory)


def record_rejection(attraction: str, reason: str = "") -> str:
    memory = load_user_memory()
    memory["rejected_recommendations"].append({
        "attraction": attraction,
        "reason": reason or "用户未说明原因",
    })
    memory["consecutive_rejections"] = memory.get("consecutive_rejections", 0) + 1
    save_user_memory(memory)

    if memory["consecutive_rejections"] >= 3:
        return "用户已连续拒绝3个推荐，下一步必须调用 reflect_recommendation_strategy()。"

    return format_user_memory(memory)


def reflect_recommendation_strategy() -> str:
    memory = load_user_memory()
    rejected = memory.get("rejected_recommendations", [])[-3:]
    rejected_text = "；".join(f"{item['attraction']}({item['reason']})" for item in rejected)
    preferences = "、".join(memory.get("preferences", [])) or "尚不明确"
    budget = memory.get("budget") or "尚不明确"

    memory["strategy_note"] = (
        f"用户连续拒绝了这些方案:{rejected_text}。"
        f"后续推荐需要避开相似景点，先解释取舍，并优先选择更贴近偏好({preferences})、预算({budget})、"
        "门票更稳妥、交通更轻松的备选。"
    )
    memory["consecutive_rejections"] = 0
    save_user_memory(memory)
    return format_user_memory(memory)
    
# 将所有工具函数放入一个字典，方便后续调用
available_tools = {
    "get_weather": get_weather,
    "get_attraction": get_attraction,
    "check_ticket_availability": check_ticket_availability,
    "remember_user_preference": remember_user_preference,
    "record_rejection": record_rejection,
    "reflect_recommendation_strategy": reflect_recommendation_strategy,
}



class OpenAICompatibleClient:
    """
    一个用于调用任何兼容OpenAI接口的LLM服务的客户端。
    """
    def __init__(self, model: str, api_key: str, base_url: str):
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=30)

    def generate(self, prompt: str, system_prompt: str) -> str | None:
        """调用LLM API来生成回应。"""
        print("正在调用大语言模型...")
        try:
            messages = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': prompt}
            ]
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=False
            )
            answer = response.choices[0].message.content
            print("大语言模型响应成功。")
            return answer
        except Exception as e:
            print(f"调用LLM API时发生错误: {type(e).__name__}: {e}")
            return None
        


def main() -> None:
    # --- 1. 配置LLM客户端 ---
    # 请根据您使用的服务，将这里替换成对应的凭证和地址
    openai_api_key = os.getenv("OPENAI_API_KEY")
    model_id = os.getenv("MODEL_ID", "gpt-4o-mini")
    base_url = os.getenv("BASE_URL", "https://api.openai.com/v1")

    if not openai_api_key:
        raise RuntimeError("错误: 未配置 OPENAI_API_KEY 环境变量。请在 .env 或环境中设置。")

    llm = OpenAICompatibleClient(
        model=model_id,
        api_key=openai_api_key,
        base_url=base_url
    )

    # --- 2. 初始化 ---
    default_prompt = "你好，请帮我查询一下今天北京的天气，然后根据天气推荐一个合适的旅游景点。"
    user_prompt = " ".join(sys.argv[1:]).strip() or default_prompt
    auto_capture_preferences(user_prompt)
    prompt_history = [format_user_memory(load_user_memory()), f"用户请求: {user_prompt}"]

    print(f"用户输入: {user_prompt}\n" + "="*40)

    # --- 3. 运行主循环 ---
    for i in range(8): # 设置最大循环次数
        print(f"--- 循环 {i+1} ---\n")

        # 3.1. 构建Prompt
        full_prompt = "\n".join(prompt_history)

        # 3.2. 调用LLM进行思考
        llm_output = llm.generate(full_prompt, system_prompt=AGENT_SYSTEM_PROMPT)
        if llm_output is None:
            print("任务中止: 大语言模型没有返回可解析的结果。上方错误中如果出现 insufficient_quota，请检查 OpenAI 账号额度和账单；如果是 Connection error，请检查网络、代理或 BASE_URL。")
            break

        # 模型可能会输出多余的Thought-Action，需要截断
        match = re.search(r'(Thought:.*?Action:.*?)(?=\n\s*(?:Thought:|Action:|Observation:)|\Z)', llm_output, re.DOTALL)
        if match:
            truncated = match.group(1).strip()
            if truncated != llm_output.strip():
                llm_output = truncated
                print("已截断多余的 Thought-Action 对")
        print(f"模型输出:\n{llm_output}\n")
        prompt_history.append(llm_output)

        # 3.3. 解析并执行行动
        action_match = re.search(r"Action: (.*)", llm_output, re.DOTALL)
        if not action_match:
            observation = "错误: 未能解析到 Action 字段。请确保你的回复严格遵循 'Thought: ... Action: ...' 的格式。"
            observation_str = f"Observation: {observation}"
            print(f"{observation_str}\n" + "="*40)
            prompt_history.append(observation_str)
            continue
        action_str = action_match.group(1).strip()

        if action_str.startswith("Finish"):
            finish_match = re.match(r"Finish\[(.*)\]", action_str, re.DOTALL)
            if not finish_match:
                observation = "错误: Finish 动作格式不正确，应为 Finish[最终答案]。"
                observation_str = f"Observation: {observation}"
                print(f"{observation_str}\n" + "="*40)
                prompt_history.append(observation_str)
                continue
            final_answer = finish_match.group(1)
            print(f"任务完成，最终答案: {final_answer}")
            break

        tool_match = re.search(r"(\w+)\((.*)\)", action_str, re.DOTALL)
        if not tool_match:
            observation = f"错误: 无法解析工具调用格式: {action_str}"
            observation_str = f"Observation: {observation}"
            print(f"{observation_str}\n" + "="*40)
            prompt_history.append(observation_str)
            continue

        tool_name = tool_match.group(1)
        args_str = tool_match.group(2)
        kwargs = dict(re.findall(r'(\w+)="([^"]*)"', args_str))

        if tool_name in available_tools:
            observation = available_tools[tool_name](**kwargs)
        else:
            observation = f"错误:未定义的工具 '{tool_name}'"

        # 3.4. 记录观察结果
        observation_str = f"Observation: {observation}"
        print(f"{observation_str}\n" + "="*40)
        prompt_history.append(observation_str)


if __name__ == "__main__":
    main()
