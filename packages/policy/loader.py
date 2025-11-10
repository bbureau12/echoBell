import yaml, pathlib, os

def load_policies(path="config/policies.yaml"):
    # If path is relative, make it relative to the project root
    if not os.path.isabs(path):
        # Get the project root (two levels up from this file)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        path = os.path.join(project_root, path)
    
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)