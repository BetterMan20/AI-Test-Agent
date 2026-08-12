from workflow.qa_workflow import QAWorkflow
from utils.file_reader import FileReader


requirement = FileReader.read(
    "input/requirement.txt"
)

workflow = QAWorkflow()

result = workflow.run(requirement)

print(result)