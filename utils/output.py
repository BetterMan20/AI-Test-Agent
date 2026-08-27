import json
import os


class Output:

    @staticmethod
    def save(filename, content):

        os.makedirs("output", exist_ok=True)

        filepath = os.path.join(
            "output",
            filename
        )

        with open(
            filepath,
            "w",
            encoding="utf-8"
        ) as f:

            if isinstance(content, (dict, list)):

                json.dump(
                    content,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            else:

                f.write(str(content))

        print(f"输出已保存：{filepath}")

        return filepath