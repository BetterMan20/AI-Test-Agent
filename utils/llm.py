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
    timeout=300
)


def extract_llm_content(message):
    """
    统一处理不同模型返回内容

    支持：

    OpenAI:
        message.content

    Reasoning模型:
        message.reasoning_content

    """

    # --------------------------------
    # 1. 标准 ChatCompletion
    # --------------------------------

    content = getattr(
        message,
        "content",
        None
    )

    if content:

        return content


    # --------------------------------
    # 2. 推理模型兼容
    # --------------------------------

    reasoning_content = getattr(
        message,
        "reasoning_content",
        None
    )

    if reasoning_content:

        return reasoning_content


    # --------------------------------
    # 3. dict结构兼容
    # --------------------------------

    if isinstance(
        message,
        dict
    ):

        content = message.get(
            "content"
        )

        if content:

            return content


        reasoning_content = message.get(
            "reasoning_content"
        )

        if reasoning_content:

            return reasoning_content


    return None



def print_response_debug(response):
    """
    LLM返回诊断
    """

    print(
        "========== LLM Response =========="
    )


    print(
        "choices数量:",
        len(response.choices)
    )


    choice = response.choices[0]


    print(
        "finish_reason:",
        getattr(
            choice,
            "finish_reason",
            None
        )
    )


    message = choice.message


    print(
        "message.content:",
        repr(
            getattr(
                message,
                "content",
                None
            )
        )
    )


    print(
        "message.reasoning_content:",
        repr(
            getattr(
                message,
                "reasoning_content",
                None
            )
        )
    )


    if getattr(
        response,
        "usage",
        None
    ):

        print(
            "usage:",
            response.usage
        )


    print(
        "=================================="
    )



def ask_llm(
    system_prompt: str,
    user_prompt: str
):

    start = time.time()


    print(
        ">>> 开始请求 LLM..."
    )

    print(
        ">>> System Prompt 长度:",
        len(system_prompt)
    )

    print(
        ">>> User Prompt 长度:",
        len(user_prompt)
    )


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


            temperature=0.2,


            max_tokens=12000,


            stream=False

        )


        elapsed = time.time() - start


        print(
            f">>> LLM API 返回，耗时：{elapsed:.2f} 秒"
        )



        # ==================================================
        # Response 基础检查
        # ==================================================

        if not response.choices:

            raise ValueError(
                "LLM 返回 choices 为空"
            )



        print_response_debug(
            response
        )



        choice = response.choices[0]


        message = choice.message



        # ==================================================
        # 统一获取模型输出
        # ==================================================

        result = extract_llm_content(
            message
        )



        if not result:


            raise ValueError(
                "LLM 返回 content 和 reasoning_content 均为空"
            )



        print(
            ">>> LLM 输出长度:",
            len(result)
        )


        return result



    except Exception as e:


        elapsed = time.time() - start


        print(
            ">>> LLM 调用失败！"
        )


        print(
            f">>> 已耗时：{elapsed:.2f} 秒"
        )


        print(
            ">>> 错误类型:",
            type(e).__name__
        )


        print(
            ">>> 错误信息:",
            e
        )


        raise










