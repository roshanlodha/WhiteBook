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

def calculate_procainamide_dose(weight_kg: float) -> dict:
    """
    Calculates Procainamide loading dose (17 mg/kg).
    """
    dose = weight_kg * 17
    return {"weight_kg": weight_kg, "loading_dose_mg": round(dose, 2), "max_dose_mg": 1000}

def calculate_map(systolic: float, diastolic: float) -> dict:
    """
    Calculates Mean Arterial Pressure (MAP).
    """
    map_val = (systolic + 2 * diastolic) / 3
    return {"systolic": systolic, "diastolic": diastolic, "mean_arterial_pressure": round(map_val, 2)}

def calculate_maintenance_fluids(weight_kg: float) -> dict:
    """
    Calculates maintenance fluid rate using the 4-2-1 rule.
    """
    if weight_kg <= 10:
        rate = weight_kg * 4
    elif weight_kg <= 20:
        rate = 40 + (weight_kg - 10) * 2
    else:
        rate = 60 + (weight_kg - 20) * 1
    return {"weight_kg": weight_kg, "maintenance_rate_ml_hr": round(rate, 2), "daily_total_ml": round(rate * 24, 2)}

def calculate_wells_pe(
    heart_rate_gt_100: bool,
    immobilization_or_surgery: bool,
    previous_vte: bool,
    hemoptysis: bool,
    malignancy: bool,
    clinical_signs_of_dvt: bool,
    alternative_diagnosis_less_likely: bool
) -> dict:
    """
    Calculates Wells' Criteria for Pulmonary Embolism.
    """
    score = 0
    if heart_rate_gt_100: score += 1.5
    if immobilization_or_surgery: score += 1.5
    if previous_vte: score += 1.5
    if hemoptysis: score += 1
    if malignancy: score += 1
    if clinical_signs_of_dvt: score += 3
    if alternative_diagnosis_less_likely: score += 3

    probability = "High" if score > 6 else "Moderate" if score >= 2 else "Low"
    return {"wells_score": score, "probability": probability}
