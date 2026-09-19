import json
import re

def extract_json(text):
    # Try to find JSON inside markdown code blocks
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if match:
        text = match.group(1)
        
    # Try to parse directly
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
        
    # Fallback to finding the first { or [ and last } or ]
    start_obj = text.find('{')
    end_obj = text.rfind('}')
    start_arr = text.find('[')
    end_arr = text.rfind(']')
    
    start = -1
    end = -1
    
    if start_obj != -1 and (start_arr == -1 or start_obj < start_arr):
        start = start_obj
        end = end_obj + 1
    elif start_arr != -1:
        start = start_arr
        end = end_arr + 1
        
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end])
        except Exception:
            pass
            
    return None
