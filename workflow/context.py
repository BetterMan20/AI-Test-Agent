class WorkflowContext:

    def __init__(self, requirement):
        self.requirement = requirement
        self.parsed = None
        self.facts = None
        self.analysis = None
        self.gaps = None
        self.test_design = None
        self.test_cases = None
        self.validation = None
        self.quality_review = None
        self.release_gate = None

    def to_dict(self):
        return {
            "parsed": self.parsed,
            "facts": self.facts,
            "analysis": self.analysis,
            "gaps": self.gaps,
            "test_design": self.test_design,
            "test_cases": self.test_cases,
            "validation": self.validation,
            "quality_review": self.quality_review,
            "release_gate": self.release_gate,
        }
