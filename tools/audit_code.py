
import ast
import os
import sys

def check_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            tree = ast.parse(f.read(), filename=filepath)
        except SyntaxError:
            print(f"❌ Syntax Error in {filepath}")
            return []

    issues = []
    
    for node in ast.walk(tree):
        # Check for async functions
        if isinstance(node, ast.AsyncFunctionDef):
            func_name = node.name
            for child in ast.walk(node):
                # 1. Blocking time.sleep
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Attribute):
                        # time.sleep
                        if child.func.attr == 'sleep' and (
                            (isinstance(child.func.value, ast.Name) and child.func.value.id == 'time') or
                            (isinstance(child.func.value, ast.Attribute) and child.func.value.attr == 'time')
                        ):
                             issues.append(f"[{os.path.basename(filepath)}:{child.lineno}] Blocking 'time.sleep' in async function '{func_name}'")
                        
                        # requests.get/post
                        if child.func.attr in ('get', 'post', 'put', 'delete', 'request') and \
                           isinstance(child.func.value, ast.Name) and child.func.value.id == 'requests':
                             issues.append(f"[{os.path.basename(filepath)}:{child.lineno}] Blocking 'requests.{child.func.attr}' in async function '{func_name}'")

    # Check for bare except
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                issues.append(f"[{os.path.basename(filepath)}:{node.lineno}] Bare 'except:' clause (Risk: hides crashes)")

    return issues

def main():
    # Adjust root dir logic to work when run from tools/ or root
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir) # Assuming tools/ is inside root
    target_dir = os.path.join(project_root, "chintu")
    
    print(f"🔍 Auditing code in {target_dir}...")
    
    all_issues = []
    
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            if file.endswith(".py"):
                full_path = os.path.join(root, file)
                issues = check_file(full_path)
                all_issues.extend(issues)

    if all_issues:
        print("\n🚨 Potential Issues Found:")
        for issue in all_issues:
            print(issue)
        print(f"\nTotal Issues: {len(all_issues)}")
    else:
        print("\n✅ Codebase looks clean! No blocking calls or bare excepts found.")

if __name__ == "__main__":
    main()
