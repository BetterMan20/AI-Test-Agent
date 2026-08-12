from pathlib import Path


class FileReader:

    @staticmethod
    def read(path):

        return Path(path).read_text(
            encoding="utf-8"
        )