from openai import OpenAI
from config import API_KEY, BASE_URL

client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL
)

models = client.models.list()

print("====== 可用模型 ======")

for model in models.data:
    print(model.id)