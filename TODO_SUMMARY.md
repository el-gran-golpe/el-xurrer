# TODO Summary for El Xurrer Repository

This document provides a comprehensive list of all TODO and FIXME comments found in the repository, organized by file and priority level.

## 📊 Summary Statistics
- **Total TODOs**: 13
- **Total FIXMEs**: 9  
- **Files with pending tasks**: 10
- **Total items**: 22

## 🔧 High Priority Items (Infrastructure & Security)

### Dockerfile
1. **Line 5**: `# TODO: Run this as non-root user`
   - **Priority**: HIGH (Security)
   - **Context**: Container security best practice
   
2. **Line 9**: `# TODO: reduce size of the image`
   - **Priority**: MEDIUM (Performance)
   - **Context**: Current run layer is about 7.x GB in size
   
3. **Line 28**: `# TODO: this should be a volume`
   - **Priority**: MEDIUM (Architecture)
   - **Context**: resources/ directory should be mounted as volume

## 🤖 LLM Module Issues

### llm/base_llm.py
4. **Line 169**: `# FIXME: What is this for? ask Haru`
   - **Priority**: MEDIUM (Code Clarity)
   - **Context**: _update_conversation_before_model_pass method
   
5. **Line 180**: `# FIXME: What is this for? ask Haru`
   - **Priority**: MEDIUM (Code Clarity)
   - **Context**: _update_conversation_after_model_pass method
   
6. **Line 230**: `# TODO: That's for non-gpt models that seems to not return a finish reason`
   - **Priority**: HIGH (Compatibility)
   - **Context**: Model compatibility handling
   
7. **Line 256**: `# FIXME: This is a problem for unattended running`
   - **Priority**: HIGH (Reliability)
   - **Context**: finish_reason assertion that could break automation
   
8. **Line 296**: `# TODO: remove unused code`
   - **Priority**: LOW (Code Cleanup)
   - **Context**: structured_json parameter
   
9. **Line 321**: `# FIXME: This can be done in a way more explicit, for example using a flag and it has to be specific for OpenAI and Azure because the API is different`
   - **Priority**: MEDIUM (Code Quality)
   - **Context**: API handling differences
   
10. **Line 509**: `# TODO: why is this a for loop? This is called for a conversation that seems to be composed of system_prompt and prompt`
    - **Priority**: MEDIUM (Logic Review)
    - **Context**: merge_system_messages_with_user method
    
11. **Line 590**: `# FIXME: ask Haru what is the use of that`
    - **Priority**: MEDIUM (Code Understanding)
    - **Context**: function_call parameter usage

### llm/constants.py
12. **Line 7**: `# TODO: learn how this works`
    - **Priority**: MEDIUM (Documentation)
    - **Context**: DeepSeek-R1 model configuration

## 🌐 API Integration Issues

### automation/meta_api/graph_api.py
13. **Line 82**: `# TODO: check this upload_time and the img_Paths`
    - **Priority**: MEDIUM (Validation)
    - **Context**: Instagram post upload method
    
14. **Line 189**: `# FIXME: upload_time_str is not used, so now facebook publications are post immediately`
    - **Priority**: HIGH (Functionality)
    - **Context**: Facebook scheduling not working as intended

## 📝 Main Application TODOs

### mains/main_meta_typer.py
15. **Line 123**: `# TODO: fix this`
    - **Priority**: HIGH (Unclear Issue)
    - **Context**: PublicationsGenerator initialization - needs investigation

### mains/main_fanvue_typer.py
16. **Line 127**: `# TODO: When executing the full pipeline, we should make this dynamic`
    - **Priority**: MEDIUM (Enhancement)
    - **Context**: ComfyLocal instance creation should be dynamic
    
17. **Line 240**: `# TODO: I don't like using profile indexes, I prefer profile names. but meh, let's leave it for now.`
    - **Priority**: LOW (UX Improvement)
    - **Context**: Profile selection mechanism

## 🔧 Core Components

### main_components/profile.py
18. **Line 34**: `# TODO: we might be able to use Pydantic models instead of doing manual validations`
    - **Priority**: MEDIUM (Code Quality)
    - **Context**: Data validation improvement

### main_components/planning_manager.py
19. **Line 100**: `# TODO: check if the previous_storyline is correctly implemented, that is, it's not being used when the initial conditions are set to false.`
    - **Priority**: MEDIUM (Logic Validation)
    - **Context**: Storyline implementation verification needed

### main_components/posting_scheduler.py
20. **Line 90**: `# TODO: isn't it easier if you just iterate through week folders?`
    - **Priority**: LOW (Optimization)
    - **Context**: Folder iteration logic
    
21. **Line 110**: `# TODO: do I really need this day_folder?`
    - **Priority**: LOW (Code Review)
    - **Context**: Publication dataclass parameter
    
22. **Line 127**: `# TODO: uncomment when cleanup is needed (when finished the refactoring)`
    - **Priority**: LOW (Cleanup)
    - **Context**: Cleanup method call
    
23. **Line 158**: `# TODO: Should we raise in here?`
    - **Priority**: MEDIUM (Error Handling)
    - **Context**: Exception handling strategy
    
24. **Line 184**: `# TODO: remove this sleep in the future`
    - **Priority**: LOW (Performance)
    - **Context**: Selenium upload delay

### main_components/publications_generator.py
25. **Line 15**: `# TODO: Here maybe Moi knows how to use Pydantic models instead of dataclasses (ask him)`
    - **Priority**: MEDIUM (Code Quality)
    - **Context**: Data modeling improvement
    
26. **Line 78**: `# TODO: Add type hint for generator if possible`
    - **Priority**: LOW (Type Safety)
    - **Context**: ImageService class
    
27. **Line 145**: `# TODO: I have to check if Platform is a valid type for platform_name`
    - **Priority**: MEDIUM (Type Safety)
    - **Context**: PublicationsGenerator initialization

### generation_tools/utils/utils.py
28. **Line 37**: `# TODO: Accept complete phrases`
    - **Priority**: LOW (Feature Enhancement)
    - **Context**: Word processing function

## 🎯 Recommended Action Plan

### Immediate (High Priority)
1. Fix Facebook scheduling issue (upload_time not working)
2. Address unattended running assertion issue in base_llm.py
3. Investigate and fix the unclear "TODO: fix this" in main_meta_typer.py
4. Implement non-root user in Dockerfile for security

### Short Term (Medium Priority)
1. Clarify unclear FIXME comments by consulting with Haru
2. Improve API handling differences between OpenAI and Azure
3. Validate storyline implementation logic
4. Consider Pydantic model migration for better data validation

### Long Term (Low Priority)
1. Code cleanup and optimization
2. UX improvements (profile names vs indexes)
3. Type safety improvements
4. Performance optimizations

## 📋 Notes
- Many TODOs reference consulting with team members (Haru, Moi)
- Several items relate to code quality improvements (Pydantic models, type hints)
- Security and functionality issues should be prioritized
- Some TODOs are documentation/understanding related