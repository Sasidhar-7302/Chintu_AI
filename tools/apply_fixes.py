
import os

def fix_main():
    path = r"c:\Users\Sasidhar Yepuri\Desktop\My_Projects\Chimptu\main.py"
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Enable wake word by default
    old_wake = 'self.state_manager.update_feature("wake_word", enabled=True, status="inactive")'
    new_wake = 'self.state_manager.update_feature("wake_word", enabled=True, status="active")'
    
    # Enable voice commands by default
    old_voice = 'self.state_manager.update_feature("voice_commands", enabled=True, status="inactive")'
    new_voice = 'self.state_manager.update_feature("voice_commands", enabled=True, status="active")'
    
    # Enable App Control
    old_app = 'self.state_manager.update_feature("app_control", enabled=True, status="inactive")'
    new_app = 'self.state_manager.update_feature("app_control", enabled=True, status="active")'

    # Enable LLM
    old_llm = 'self.state_manager.update_feature("llm_integration", enabled=True, status="inactive")'
    new_llm = 'self.state_manager.update_feature("llm_integration", enabled=True, status="active")'

    # Enable Job Search
    old_job = 'self.state_manager.update_feature("job_search", enabled=True, status="inactive")'
    new_job = 'self.state_manager.update_feature("job_search", enabled=True, status="active")'
    
    if old_wake in content:
        content = content.replace(old_wake, new_wake)
        content = content.replace(old_voice, new_voice)
        content = content.replace(old_app, new_app)
        content = content.replace(old_llm, new_llm)
        content = content.replace(old_job, new_job)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print("Fixed main.py")
    else:
        print("Could not find target strings in main.py")

def fix_router():
    path = r"c:\Users\Sasidhar Yepuri\Desktop\My_Projects\Chimptu\chintu\core\model_router.py"
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    old_router = 'return RoutingDecision(Intent.SIMPLE_CHAT, TaskComplexity.SIMPLE, True, True, {"query": text})'
    new_router = 'return RoutingDecision(Intent.SIMPLE_CHAT, TaskComplexity.SIMPLE, True, False, {"query": text})'
    
    if old_router in content:
        content = content.replace(old_router, new_router)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print("Fixed model_router.py")
    else:
        print("Could not find target strings in model_router.py")

if __name__ == "__main__":
    fix_main()
    fix_router()
