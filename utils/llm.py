import time

from openai import OpenAI
from config import API_KEY, BASE_URL, MODEL


print("========== LLM Config ==========")
print("BASE_URL:", BASE_URL)
print("MODEL:", MODEL)
print("===============================")


client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
    timeout=180
)


def ask_llm(system_prompt: str, user_prompt: str):

    start = time.time()

    print(">>> 开始请求 LLM...")
    print(">>> System Prompt 长度:", len(system_prompt))
    print(">>> User Prompt 长度:", len(user_prompt))

    try:

        response = client.chat.completions.create(
            model=MODEL,

            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],

            temperature=1,

            max_tokens=12000
        )

        elapsed = time.time() - start

        print(f">>> LLM 返回成功，耗时：{elapsed:.2f} 秒")

        result = response.choices[0].message.content

        print(">>> LLM 输出长度:", len(result))

        return result

    except Exception as e:

        elapsed = time.time() - start

        print(">>> LLM 调用失败！")
        print(f">>> 已耗时：{elapsed:.2f} 秒")
        print(">>> 错误类型:", type(e).__name__)
        print(">>> 错误信息:", e)

        raise