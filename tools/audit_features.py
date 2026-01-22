
import ast
import os

CAPABILITY_FILE = r"c:\Users\Sasidhar Yepuri\Desktop\My_Projects\Chimptu\chintu\core\capability_handlers.py"

def audit_features():
    print(f"🔍 Auditing features in {CAPABILITY_FILE}...")
    
    with open(CAPABILITY_FILE, 'r', encoding='utf-8') as f:
        tree = ast.parse(f.read())
        
    handlers = {}
    registrations = []
    
    # 1. First pass: Find all function definitions
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Check for empty or NotImplemented
            is_empty = False
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                is_empty = True
            
            is_not_implemented = False
            if len(node.body) == 1 and isinstance(node.body[0], ast.Raise):
                exc = node.body[0].exc
                if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name) and exc.func.id == 'NotImplementedError':
                    is_not_implemented = True
                    
            handlers[node.name] = {
                "name": node.name,
                "is_empty": is_empty,
                "is_not_implemented": is_not_implemented,
                "lines": node.end_lineno - node.lineno
            }

    # 2. Second pass: Find registrations
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # registry.register(Capability(...))
            if isinstance(node.func, ast.Attribute) and node.func.attr == 'register':
                if node.args and isinstance(node.args[0], ast.Call) and isinstance(node.args[0].func, ast.Name) and node.args[0].func.id == 'Capability':
                    cap_args = node.args[0].keywords
                    name_arg = next((k for k in cap_args if k.arg == 'name'), None)
                    handler_arg = next((k for k in cap_args if k.arg == 'handler'), None)
                    
                    if name_arg and isinstance(name_arg.value, ast.Constant):
                        cap_name = name_arg.value.value
                        handler_name = "Unknown"
                        
                        if handler_arg:
                            if isinstance(handler_arg.value, ast.Name):
                                handler_name = handler_arg.value.id
                        
                        registrations.append({
                            "capability": cap_name,
                            "handler": handler_name
                        })

    # 3. Correlate
    print(f"\nFound {len(registrations)} registered capabilities.")
    print("-" * 60)
    print(f"{'Capability':<25} | {'Handler':<30} | {'Status':<15}")
    print("-" * 60)
    
    passed = 0
    failed = 0
    
    for reg in registrations:
        cap = reg['capability']
        handler_name = reg['handler']
        status = "❓ Unknown"
        
        if handler_name in handlers:
            h_info = handlers[handler_name]
            if h_info['is_empty']:
                status = "❌ Empty"
                failed += 1
            elif h_info['is_not_implemented']:
                status = "❌ NotImpl"
                failed += 1
            else:
                status = "✅ Implemented"
                passed += 1
        else:
            status = "❌ Missing Handler"
            failed += 1
            
        print(f"{cap:<25} | {handler_name:<30} | {status:<15}")

    print("-" * 60)
    print(f"Summary: {passed} Implemented, {failed} Issues")

if __name__ == "__main__":
    audit_features()
