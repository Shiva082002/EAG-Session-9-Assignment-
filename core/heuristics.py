"""
Heuristics module for the Cortex-R Agent.

This module provides functions for validating and transforming:
1. User inputs before sending to the LLM
2. LLM responses before execution

These heuristics help improve reliability, safety, and consistency.
"""

import re
import json
from typing import Dict, List, Any, Optional, Union, Tuple, Set

# Import custom log function
try:
    from agent import log
except ImportError:
    import datetime
    def log(stage: str, msg: str):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] [{stage}] {msg}")

# Constants
MAX_INPUT_LENGTH = 15000  # Characters (adjust based on model context window)
MIN_INPUT_LENGTH = 2  # Characters
BANNED_WORDS = [
    # Add words that should be filtered from input
    "hackme", "exploit", "bypass", "malicious",
]
SENSITIVE_PATTERNS = [
    r'\b\d{16}\b',  # Credit card numbers (simple pattern)
    r'\b\d{3}-\d{2}-\d{4}\b',  # SSN
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email addresses
]

# Function signature keywords for detection
FUNCTION_PATTERNS = [
    r'^\s*(async\s+)?def\s+solve\s*\(',  # solve() function detection
    r'FINAL_ANSWER:',  # Final answer pattern
    r'FURTHER_PROCESSING_REQUIRED:',  # Further processing pattern
]

# Input validation functions
def validate_input_length(text: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check if input text is within acceptable length bounds.
    
    Args:
        text: Input text from user
        
    Returns:
        Tuple of (is_valid, error_message, fixed_text)
    """
    if len(text) > MAX_INPUT_LENGTH:
        truncated = text[:MAX_INPUT_LENGTH - 100] + "... [truncated due to length]"
        return False, f"Input exceeds maximum length of {MAX_INPUT_LENGTH} characters", truncated
    
    if len(text) < MIN_INPUT_LENGTH:
        return False, f"Input is too short (min {MIN_INPUT_LENGTH} characters required)", text
    
    return True, None, text

def filter_banned_words(text: str) -> Tuple[bool, Optional[str], str]:
    """
    Remove or censor banned words from input.
    
    Args:
        text: Input text from user
        
    Returns:
        Tuple of (is_changed, message, cleaned_text)
    """
    original_text = text
    changed = False
    
    for word in BANNED_WORDS:
        if re.search(r'\b' + re.escape(word) + r'\b', text, re.IGNORECASE):
            # Replace with asterisks
            text = re.sub(r'\b' + re.escape(word) + r'\b', '*' * len(word), text, flags=re.IGNORECASE)
            changed = True
    
    if changed:
        return True, "Some words were filtered for safety reasons", text
    
    return False, None, text

def redact_sensitive_information(text: str) -> Tuple[bool, Optional[str], str]:
    """
    Identify and redact potentially sensitive information.
    
    Args:
        text: Input text from user
        
    Returns:
        Tuple of (is_changed, message, redacted_text)
    """
    original_text = text
    changed = False
    
    for pattern in SENSITIVE_PATTERNS:
        matches = re.finditer(pattern, text)
        for match in matches:
            # Replace with redacted text
            text = text.replace(match.group(0), "[REDACTED]")
            changed = True
    
    if changed:
        return True, "Some potentially sensitive information was redacted", text
    
    return False, None, text

def normalize_query(text: str) -> str:
    """
    Normalize the query text to improve matching with historical queries.
    
    Args:
        text: Input text from user
        
    Returns:
        Normalized text
    """
    # Convert to lowercase
    text = text.lower()
    
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove punctuation except when meaningful (e.g. URLs, file paths)
    text = re.sub(r'[,.;:!?"\'](?!\S)', ' ', text)
    
    return text

def check_mathematical_expressions(text: str) -> Tuple[bool, Optional[str], str]:
    """
    Check for and normalize mathematical expressions.
    
    Args:
        text: Input text from user
        
    Returns:
        Tuple of (is_changed, message, fixed_text)
    """
    # Look for math expressions like "what is 5+5" or "calculate 10*3"
    math_patterns = [
        r'what\s+is\s+([\d\s\+\-\*\/\(\)]+)',
        r'calculate\s+([\d\s\+\-\*\/\(\)]+)',
        r'compute\s+([\d\s\+\-\*\/\(\)]+)',
        r'evaluate\s+([\d\s\+\-\*\/\(\)]+)',
        r'solve\s+([\d\s\+\-\*\/\(\)]+)'
    ]
    
    for pattern in math_patterns:
        matches = re.search(pattern, text, re.IGNORECASE)
        if matches:
            expression = matches.group(1).strip()
            # Format it as a cleaner math query
            formatted_text = f"Calculate the result of the expression: {expression}"
            return True, "Detected mathematical expression", formatted_text
    
    return False, None, text

# Output validation functions
def validate_function_format(text: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validate that the LLM response contains a valid solve() function.
    
    Args:
        text: LLM response text
        
    Returns:
        Tuple of (is_valid, error_message, fixed_text)
    """
    if not re.search(FUNCTION_PATTERNS[0], text, re.MULTILINE):
        # Check if there's Python code but not wrapped in solve()
        if re.search(r'(import\s+|await\s+|def\s+|return\s+)', text):
            # Try to wrap it in solve()
            lines = text.split('\n')
            in_code_block = False
            in_function = False
            fixed_lines = ["async def solve():"]
            
            for line in lines:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                
                if in_code_block or not line.strip().startswith("```"):
                    # Indent the line
                    if line.strip():
                        fixed_lines.append("    " + line)
                    else:
                        fixed_lines.append("")
            
            fixed_text = "\n".join(fixed_lines)
            return False, "Missing solve() function, attempted to fix", fixed_text
        else:
            # If it looks like a final answer directly, wrap it in a solve function
            if text.strip().startswith("FINAL_ANSWER:") or "FINAL_ANSWER:" in text:
                answer_part = text.split("FINAL_ANSWER:")[1].strip() if "FINAL_ANSWER:" in text else text
                fixed_text = f"async def solve():\n    return \"FINAL_ANSWER: {answer_part}\""
                return False, "Missing solve() function, created a direct answer function", fixed_text
            
            # Not fixable
            return False, "Response does not contain a valid solve() function", None
    
    return True, None, text

def extract_code_blocks(text: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Extract code blocks from markdown formatting.
    
    Args:
        text: LLM response text
        
    Returns:
        Tuple of (is_changed, message, extracted_code)
    """
    # Look for Python code blocks
    code_block_matches = re.search(r'```(?:python)?\s*(.*?)```', text, re.DOTALL)
    
    if code_block_matches:
        code = code_block_matches.group(1).strip()
        if re.search(FUNCTION_PATTERNS[0], code, re.MULTILINE):
            return True, "Extracted code from markdown block", code
    
    return False, None, text

def check_imports_completeness(text: str) -> Tuple[bool, Optional[str], str]:
    """
    Check if the code has all necessary imports mentioned in the body.
    
    Args:
        text: LLM-generated code
        
    Returns:
        Tuple of (is_changed, message, fixed_code)
    """
    # List of commonly used modules in the agent
    common_modules = {
        "json": "json",
        "re": "re",
        "asyncio": "asyncio",
        "datetime": "datetime",
        "math": "math",
        "os": "os",
        "sys": "sys",
    }
    
    code_lines = text.split('\n')
    imported_modules = set()
    needed_modules = set()
    
    # Find existing imports
    for line in code_lines:
        if re.match(r'^\s*import\s+(\w+)', line):
            module = re.match(r'^\s*import\s+(\w+)', line).group(1)
            imported_modules.add(module)
        elif re.match(r'^\s*from\s+(\w+)\s+import', line):
            module = re.match(r'^\s*from\s+(\w+)\s+import', line).group(1)
            imported_modules.add(module)
    
    # Identify needed modules
    for module, module_name in common_modules.items():
        # Check if module is used but not imported
        module_pattern = r'\b' + re.escape(module) + r'\.'
        if re.search(module_pattern, text) and module_name not in imported_modules:
            needed_modules.add(module_name)
    
    # Add missing imports if needed
    if needed_modules:
        import_statements = [f"import {module}" for module in needed_modules]
        fixed_code = "\n".join(import_statements) + "\n" + text
        return True, f"Added missing imports: {', '.join(needed_modules)}", fixed_code
    
    return False, None, text

def validate_return_format(text: str) -> Tuple[bool, Optional[str], str]:
    """
    Check if the code properly returns FINAL_ANSWER or FURTHER_PROCESSING_REQUIRED.
    
    Args:
        text: LLM-generated code
        
    Returns:
        Tuple of (is_valid, error_message, fixed_code)
    """
    # Check for return statements
    return_statements = re.findall(r'return\s+(.*?)(?:\n|$)', text)
    
    # If no return statements found
    if not return_statements:
        if "FINAL_ANSWER:" in text:
            # Extract answer and add proper return
            answer_part = text.split("FINAL_ANSWER:")[1].strip().split('\n')[0]
            fixed_lines = text.split('\n')
            fixed_lines.append(f'    return "FINAL_ANSWER: {answer_part}"')
            return False, "Added missing return statement with FINAL_ANSWER", "\n".join(fixed_lines)
        return False, "No return statement found", text
    
    # Check if return values have proper format
    valid_formats = ["FINAL_ANSWER:", "FURTHER_PROCESSING_REQUIRED:"]
    has_valid_format = False
    
    for stmt in return_statements:
        for format in valid_formats:
            if format in stmt:
                has_valid_format = True
                break
    
    if not has_valid_format:
        # Try to fix returns that don't have proper prefixes
        fixed_code = text
        for stmt in return_statements:
            # If return looks like a direct answer without the prefix
            if not any(format in stmt for format in valid_formats):
                cleaned_stmt = stmt.strip('"').strip("'")
                fixed_return = f'return "FINAL_ANSWER: {cleaned_stmt}"'
                fixed_code = fixed_code.replace(f"return {stmt}", fixed_return)
        
        return False, "Fixed return statements to include FINAL_ANSWER prefix", fixed_code
    
    return True, None, text

def check_await_calls(text: str) -> Tuple[bool, Optional[str], str]:
    """
    Check if async calls are properly awaited.
    
    Args:
        text: LLM-generated code
        
    Returns:
        Tuple of (is_changed, message, fixed_code)
    """
    # Common patterns that should be awaited
    async_patterns = [
        r'mcp\.call_tool\(', 
        r'dispatcher\.call_tool\(',
        r'run_python_sandbox\(',
        r'run_perception\(',
        r'model\.generate_text\(',
    ]
    
    code_lines = text.split('\n')
    fixed_code_lines = []
    changed = False
    
    for line in code_lines:
        # Check if line contains an async call that isn't awaited
        for pattern in async_patterns:
            if re.search(pattern, line) and "await " not in line:
                # Only fix if it's an assignment or standalone call
                if "=" in line or line.strip().endswith(")"):
                    # Add await
                    line = line.replace(pattern, "await " + pattern.replace("\\", ""))
                    changed = True
        
        fixed_code_lines.append(line)
    
    if changed:
        return True, "Added missing 'await' keywords to async function calls", "\n".join(fixed_code_lines)
    
    return False, None, text

def check_unsafe_code_patterns(text: str) -> Tuple[bool, Optional[str], str]:
    """
    Check for potentially unsafe code patterns in LLM responses.
    
    Args:
        text: LLM-generated code
        
    Returns:
        Tuple of (is_dangerous, message, fixed_code)
    """
    dangerous_patterns = [
        r'os\.system\(',
        r'subprocess\.',
        r'eval\(',
        r'exec\(',
        r'__import__\(',
        r'open\(.+?[\'"]w[\'"]\)',  # File writing
        r'shutil\.rmtree',  # Directory deletion
        r'\.delete\(\)',    # Object deletion methods
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            # Flag but don't modify - let human review
            return True, f"Potentially unsafe code pattern detected: {pattern}", text
    
    return False, None, text

def validate_json_strings(text: str) -> Tuple[bool, Optional[str], str]:
    """
    Find and validate JSON strings in the code to ensure they're properly formatted.
    
    Args:
        text: LLM-generated code
        
    Returns:
        Tuple of (is_fixed, message, fixed_code)
    """
    # Find JSON-like strings
    json_patterns = re.finditer(r'(?:json\.loads\()?\s*[\'"](\{.*?\})[\'"]', text, re.DOTALL)
    
    fixed_text = text
    fixed = False
    
    for match in json_patterns:
        json_str = match.group(1)
        try:
            # Try to parse it properly
            json_obj = json.loads(json_str.replace("'", '"'))
            # No error means it's valid
        except json.JSONDecodeError:
            # Try to fix common JSON formatting issues
            fixed_json = json_str.replace("'", '"')
            fixed_json = re.sub(r'(\w+):', r'"\1":', fixed_json)  # Convert keys to double-quoted
            
            try:
                json.loads(fixed_json)
                fixed_text = fixed_text.replace(json_str, fixed_json)
                fixed = True
            except:
                # If still invalid, just flag it
                pass
    
    if fixed:
        return True, "Fixed malformed JSON in code", fixed_text
    
    return False, None, text

def check_infinite_loops(text: str) -> Tuple[bool, Optional[str], str]:
    """
    Detect potential infinite loops in the code.
    
    Args:
        text: LLM-generated code
        
    Returns:
        Tuple of (has_issue, message, fixed_code)
    """
    # Check for while loops without clear exit conditions
    infinite_patterns = [
        r'while\s+True.*?(?!break)',  # while True without break
        r'while\s+\w+.*?(?!\w+\s*[+\-*/]=)',  # while var without var modification
        r'for\s+\w+\s+in\s+\w+.*?(?!\w+\s*[+\-*/]=)'  # for loop without var modification
    ]
    
    fixed_text = text
    has_issue = False
    
    for pattern in infinite_patterns:
        if re.search(pattern, text, re.DOTALL):
            # Add a safety counter to the loop
            loops = re.findall(r'(while\s+True.*?:)', text, re.DOTALL)
            for loop in loops:
                if 'break' not in loop:
                    safety_loop = loop + "\n    safety_counter = 0\n"
                    safety_check = "    safety_counter += 1\n    if safety_counter > 1000: break  # Safety limit\n"
                    fixed_text = fixed_text.replace(loop, safety_loop)
                    # Insert the safety check after the loop body indentation
                    fixed_text = re.sub(r'(' + re.escape(safety_loop) + r'.*?\n\s+)', r'\1' + safety_check, fixed_text, flags=re.DOTALL)
                    has_issue = True
    
    if has_issue:
        return True, "Added safety counters to potential infinite loops", fixed_text
    
    return False, None, text

def check_edge_case_handling(text: str) -> Tuple[bool, Optional[str], str]:
    """
    Check if code properly handles common edge cases.
    
    Args:
        text: LLM-generated code
        
    Returns:
        Tuple of (is_fixed, message, fixed_code)
    """
    fixed_text = text
    issues_fixed = False
    
    # Check for list/dictionary access without bounds checking
    array_accesses = re.findall(r'(\w+)\[(\w+|\d+)\]', text)
    
    for access in array_accesses:
        var_name, index = access
        
        # If accessing with variable index, check if there's a bounds check nearby
        if not index.isdigit() and not re.search(rf'if\s+{index}\s*<\s*len\({var_name}\)', text):
            # Add bounds checking
            check_code = f"if {index} < len({var_name}):\n"
            # Find the line with this access
            lines = fixed_text.split('\n')
            for i, line in enumerate(lines):
                if f"{var_name}[{index}]" in line and "if" not in line:
                    indent = len(line) - len(line.lstrip())
                    indent_str = " " * indent
                    lines[i] = f"{indent_str}{check_code}{indent_str}    {line.strip()}\n{indent_str}else:\n{indent_str}    # Handle index out of bounds\n{indent_str}    pass"
                    issues_fixed = True
                    break
            
            fixed_text = '\n'.join(lines)
    
    # Check for dict access without .get() or key checking
    dict_accesses = re.findall(r'(\w+)\[[\'"](.*?)[\'"]\]', text)
    
    for access in dict_accesses:
        dict_name, key = access
        if not re.search(rf'if\s+[\'"]?{key}[\'"]?\s+in\s+{dict_name}', text) and not f"{dict_name}.get(" in text:
            # Try to replace with .get() method for safer access
            fixed_text = fixed_text.replace(f"{dict_name}[\"{key}\"]", f"{dict_name}.get(\"{key}\")")
            fixed_text = fixed_text.replace(f"{dict_name}['{key}']", f"{dict_name}.get('{key}')")
            issues_fixed = True
    
    if issues_fixed:
        return True, "Added edge case handling for collections access", fixed_text
    
    return False, None, text

def check_variable_naming_consistency(text: str) -> Tuple[bool, Optional[str], str]:
    """
    Check for and fix inconsistencies in variable naming conventions.
    
    Args:
        text: LLM-generated code
        
    Returns:
        Tuple of (is_fixed, message, fixed_code)
    """
    # Find all variable names
    variable_names = re.findall(r'\b(\w+)\s*=', text)
    
    # Check for mixed snake_case and camelCase
    snake_case = [v for v in variable_names if '_' in v]
    camel_case = [v for v in variable_names if v[0].islower() and '_' not in v and any(c.isupper() for c in v)]
    
    # If mixed conventions found with a majority of one type, convert to the dominant style
    if snake_case and camel_case:
        if len(snake_case) > len(camel_case):
            # Convert camelCase to snake_case
            fixed_text = text
            for var in camel_case:
                snake_var = ''.join(['_'+c.lower() if c.isupper() else c for c in var]).lstrip('_')
                fixed_text = re.sub(r'\b' + re.escape(var) + r'\b', snake_var, fixed_text)
            return True, "Converted variable names to consistent snake_case", fixed_text
        else:
            # Convert snake_case to camelCase
            fixed_text = text
            for var in snake_case:
                camel_var = ''.join([s.capitalize() if i > 0 else s for i, s in enumerate(var.split('_'))])
                camel_var = camel_var[0].lower() + camel_var[1:] if camel_var else camel_var
                fixed_text = re.sub(r'\b' + re.escape(var) + r'\b', camel_var, fixed_text)
            return True, "Converted variable names to consistent camelCase", fixed_text
    
    return False, None, text

# Main validation functions
def validate_user_input(text: str) -> Tuple[bool, List[str], str]:
    """
    Apply all input validation heuristics and return results.
    
    Args:
        text: User input text
        
    Returns:
        Tuple of (is_valid, messages, fixed_text)
    """
    is_valid = True
    all_messages = []
    fixed_text = text
    
    # 1. Check input length
    length_valid, length_msg, length_fixed = validate_input_length(text)
    if not length_valid:
        is_valid = False
        all_messages.append(length_msg)
        fixed_text = length_fixed
    
    # 2. Filter banned words
    words_changed, words_msg, words_fixed = filter_banned_words(fixed_text)
    if words_changed:
        all_messages.append(words_msg)
        fixed_text = words_fixed
    
    # 3. Redact sensitive information
    redacted_changed, redacted_msg, redacted_fixed = redact_sensitive_information(fixed_text)
    if redacted_changed:
        all_messages.append(redacted_msg)
        fixed_text = redacted_fixed
    
    # 4. Check for mathematical expressions
    math_changed, math_msg, math_fixed = check_mathematical_expressions(fixed_text)
    if math_changed:
        all_messages.append(math_msg)
        fixed_text = math_fixed
    
    # Note: normalize_query is used separately for search comparisons
    
    return is_valid, all_messages, fixed_text

def validate_llm_response(text: str) -> Tuple[bool, List[str], str]:
    """
    Apply all output validation heuristics and return results.
    
    Args:
        text: LLM response text
        
    Returns:
        Tuple of (is_valid, messages, fixed_text)
    """
    is_valid = True
    all_messages = []
    fixed_text = text
    
    # 1. Extract code blocks if present
    code_changed, code_msg, code_fixed = extract_code_blocks(fixed_text)
    if code_changed:
        all_messages.append(code_msg)
        fixed_text = code_fixed
    
    # 2. Validate function format (solve function)
    func_valid, func_msg, func_fixed = validate_function_format(fixed_text)
    if not func_valid and func_fixed:
        is_valid = False
        all_messages.append(func_msg)
        fixed_text = func_fixed
    elif not func_valid:
        is_valid = False
        all_messages.append(func_msg)
    
    # 3. Check imports completeness
    imports_changed, imports_msg, imports_fixed = check_imports_completeness(fixed_text)
    if imports_changed:
        all_messages.append(imports_msg)
        fixed_text = imports_fixed
    
    # 4. Validate return format
    return_valid, return_msg, return_fixed = validate_return_format(fixed_text)
    if not return_valid:
        all_messages.append(return_msg)
        fixed_text = return_fixed
    
    # 5. Check await calls
    await_changed, await_msg, await_fixed = check_await_calls(fixed_text)
    if await_changed:
        all_messages.append(await_msg)
        fixed_text = await_fixed
    
    # 6. Check for unsafe code patterns
    unsafe_detected, unsafe_msg, unsafe_fixed = check_unsafe_code_patterns(fixed_text)
    if unsafe_detected:
        all_messages.append(unsafe_msg)
        fixed_text = unsafe_fixed
    
    # 7. Validate JSON strings
    json_fixed, json_msg, json_fixed_text = validate_json_strings(fixed_text)
    if json_fixed:
        all_messages.append(json_msg)
        fixed_text = json_fixed_text
    
    # 8. Check for infinite loops
    loops_fixed, loops_msg, loops_fixed_text = check_infinite_loops(fixed_text)
    if loops_fixed:
        all_messages.append(loops_msg)
        fixed_text = loops_fixed_text
    
    # 9. Check edge case handling
    edge_fixed, edge_msg, edge_fixed_text = check_edge_case_handling(fixed_text)
    if edge_fixed:
        all_messages.append(edge_msg)
        fixed_text = edge_fixed_text
    
    # 10. Check variable naming consistency
    naming_fixed, naming_msg, naming_fixed_text = check_variable_naming_consistency(fixed_text)
    if naming_fixed:
        all_messages.append(naming_msg)
        fixed_text = naming_fixed_text
    
    return is_valid, all_messages, fixed_text

# Integration functions
async def apply_input_heuristics(query: str) -> Tuple[str, List[str]]:
    """
    Apply heuristics to user input and return the fixed version.
    
    Args:
        query: User input query
        
    Returns:
        Tuple of (fixed_query, messages)
    """
    is_valid, messages, fixed_query = validate_user_input(query)
    
    if messages:
        log("heuristics", f"Applied input heuristics: {messages}")
    
    return fixed_query, messages

async def apply_output_heuristics(response: str) -> Tuple[str, List[str]]:
    """
    Apply heuristics to LLM output and return the fixed version.
    
    Args:
        response: LLM response
        
    Returns:
        Tuple of (fixed_response, messages)
    """
    is_valid, messages, fixed_response = validate_llm_response(response)
    
    if messages:
        log("heuristics", f"Applied output heuristics: {messages}")
    
    return fixed_response, messages 