def calculate_math(expression: str) -> dict:
    """
    Evaluates a simple mathematical expression.
    Supports basic operators: +, -, *, /
    """
    try:
        # Using a very restricted eval-like approach for safety in this demo
        # For production, use a proper math parser
        allowed_chars = "0123456789+-*/.() "
        if not all(c in allowed_chars for c in expression):
             return {"error": "Invalid characters in expression"}
        
        result = eval(expression, {"__builtins__": {}})
        return {"expression": expression, "result": round(float(result), 2)}
    except Exception as e:
        return {"error": str(e)}
