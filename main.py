from utils.llm import ask_llm
import config

print(config.__file__)

if __name__ == "__main__":


    question = "你好，请介绍一下自己"

    result = ask_llm(question)

    print(result)