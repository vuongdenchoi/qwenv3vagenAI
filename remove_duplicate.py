import re

def process(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # We want to remove the exact duplicate block we added.
    # The block we added starts with "def extract_user_context" and ends right before "\n\n@app.post(\"/chat\")" (which was fixed)
    # Let's find the SECOND occurrence of `def extract_user_context(user_text: str) -> Tuple[bool, Dict[str, Optional[str]]]:`
    
    parts = content.split('def extract_user_context(user_text: str) -> Tuple[bool, Dict[str, Optional[str]]]:')
    
    if len(parts) == 3:
        # parts[0] is everything before the first occurrence
        # parts[1] is the body of the first occurrence + everything up to the second occurrence
        # parts[2] is the body of the second occurrence (the duplicate) up to the end of the file
        
        # We need to find where the duplicate ends. The duplicate ends right before @app.post("/chat")
        body_parts = parts[2].split('@app.post("/chat")', 1)
        if len(body_parts) == 2:
            new_content = parts[0] + 'def extract_user_context(user_text: str) -> Tuple[bool, Dict[str, Optional[str]]]:' + parts[1] + '@app.post("/chat")' + body_parts[1]
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print("Duplicate removed successfully.")
        else:
            print("Could not find @app.post('/chat') after duplicate.")
    else:
        print(f"Found {len(parts)-1} occurrences, expected 2.")

process('backend/main.py')
