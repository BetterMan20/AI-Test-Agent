from openai import OpenAI

from config import API_KEY, BASE_URL, MODEL


client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL
)


def ask_llm(prompt):

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "你是一名高级软件测试工程师"
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return response.choices[0].message.content