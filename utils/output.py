import os


class Output:

    @staticmethod
    def save(filename, content):

        os.makedirs("output", exist_ok=True)

        with open(
            f"output/{filename}",
            "w",
            encoding="utf-8"
        ) as f:

            f.write(content)

        print(f"{filename} 已保存")